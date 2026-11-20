//! The dev run's sidecar spawn, exercised headlessly (fix/dev-launch, 2026-11-13).
//!
//! After the beta merge the owner's `npm run tauri dev` failed with "Could not start the
//! engine sidecar: No such file or directory (os error 2)". Nothing caught it: no test built
//! the dev configuration. This test builds the app exactly as the dev run does — the
//! capabilities `tauri.conf.json` compiles in, the same plugins (`with_plugins`) — on Tauri's
//! mock runtime, so no window opens and nothing reaches the screen. Then it makes the IPC call
//! the webview makes (`sidecar.ts`: `Command.create('zugzwang-sidecar', [SIDECAR_SCRIPT])`),
//! which goes through the real ACL, the real shell scope and a real process spawn, and waits
//! for the sidecar's `ready` event on its stdout.
//!
//! The sidecar gets its own database and data folder in a temporary directory
//! (`ZUGZWANG_DB`, `ZUGZWANG_DATA_DIR`), so it never opens `~/.zugzwang`. The app id is
//! replaced for the test so it never shares one with an app the owner has open.
//!
//! It needs the interpreter `capabilities/default.json` names, `$HOME/zugzwang/.venv/bin/python`
//! (the dev run's convention; CI links its checkout there).

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::ipc::{CallbackFn, InvokeBody, InvokeResponseBody};
use tauri::test::{get_ipc_response, mock_builder, MockRuntime, INVOKE_KEY};
use tauri::webview::InvokeRequest;
use tauri::{WebviewWindow, WebviewWindowBuilder};

const CHANNEL_ID: u32 = 4242;
const READY_TIMEOUT: Duration = Duration::from_secs(120);

fn request(cmd: &str, body: Value) -> InvokeRequest {
  InvokeRequest {
    cmd: cmd.into(),
    callback: CallbackFn(0),
    error: CallbackFn(1),
    url: "tauri://localhost".parse().unwrap(),
    body: InvokeBody::Json(body),
    headers: Default::default(),
    invoke_key: INVOKE_KEY.to_string(),
  }
}

fn sidecar_script() -> PathBuf {
  // The same derivation as desktop/vite.config.ts: <desktop>/../sidecar/main.py.
  PathBuf::from(env!("CARGO_MANIFEST_DIR"))
    .join("../../sidecar/main.py")
    .canonicalize()
    .expect("sidecar/main.py beside desktop/")
}

/// One JSON object per stdout line the sidecar printed, as the webview's channel received them.
fn stdout_events(messages: &[String]) -> Vec<Value> {
  messages
    .iter()
    .filter_map(|m| serde_json::from_str::<Value>(m).ok())
    .filter(|m| m["event"] == "Stdout")
    .filter_map(|m| m["payload"].as_str().and_then(|s| serde_json::from_str(s).ok()))
    .collect()
}

#[test]
fn dev_configuration_spawns_the_sidecar() {
  let messages: Arc<Mutex<Vec<String>>> = Arc::default();
  let sink = messages.clone();

  let mut context = crate::context::<MockRuntime>();
  // Never the dev run's or the beta's id (CLAUDE.md: no build that shares an app id with
  // something the owner has open). The id plays no part in capabilities or the shell scope.
  context.config_mut().identifier = "dev.zugzwang.headless-test".into();

  let app = crate::with_plugins(mock_builder())
    .channel_interceptor(move |_webview, callback, _index, body| {
      if callback.0 == CHANNEL_ID {
        if let InvokeResponseBody::Json(s) = body {
          sink.lock().unwrap().push(s.clone());
        }
        return true;
      }
      false
    })
    .build(context)
    .expect("the dev configuration builds");
  let webview: WebviewWindow<MockRuntime> =
    WebviewWindowBuilder::new(&app, "main", Default::default())
      .build()
      .expect("the main window (mock)");

  let tmp = std::env::temp_dir().join(format!("zugzwang-dev-spawn-{}", std::process::id()));
  std::fs::create_dir_all(&tmp).unwrap();
  let db = tmp.join("zugzwang.db");
  let script = sidecar_script();

  let spawned = get_ipc_response(
    &webview,
    request(
      "plugin:shell|spawn",
      json!({
        "program": "zugzwang-sidecar",
        "args": [script.to_string_lossy()],
        "options": {
          "env": {
            "ZUGZWANG_DB": db.to_string_lossy(),
            "ZUGZWANG_DATA_DIR": tmp.to_string_lossy(),
          }
        },
        "onEvent": format!("__CHANNEL__:{CHANNEL_ID}"),
      }),
    ),
  );
  let pid = match spawned {
    Ok(body) => body.deserialize::<u32>().expect("spawn returns a pid"),
    Err(e) => panic!(
      "the dev configuration cannot spawn the sidecar (the 2026-11-13 dev-launch failure \
       looked like this): {e}"
    ),
  };

  let started = Instant::now();
  let ready = loop {
    let events = stdout_events(&messages.lock().unwrap());
    if let Some(ready) = events.into_iter().find(|e| e["event"] == "ready") {
      break Some(ready);
    }
    let terminated = messages
      .lock()
      .unwrap()
      .iter()
      .any(|m| m.contains("\"Terminated\""));
    if terminated || started.elapsed() > READY_TIMEOUT {
      break None;
    }
    std::thread::sleep(Duration::from_millis(100));
  };

  let _ = get_ipc_response(&webview, request("plugin:shell|kill", json!({ "cmd": "killChild", "pid": pid })));
  let all = messages.lock().unwrap().join("\n");
  let _ = std::fs::remove_dir_all(&tmp);

  let ready = ready.unwrap_or_else(|| {
    panic!("the sidecar spawned (pid {pid}) but never emitted `ready`; what it printed:\n{all}")
  });
  // `ok` is false when no Stockfish is found (a bare CI checkout); the spawn path is what is
  // under test, and `ready` proves the sidecar booted, migrated its own database and answered.
  assert!(ready["data"].get("ok").is_some(), "ready carries ok: {ready}");
  assert!(db.parent().is_some());
  eprintln!(
    "dev spawn: ready in {:.1} s, {}",
    started.elapsed().as_secs_f64(),
    ready
  );
}
