use tauri::{Builder, Runtime};

/// The plugins every build loads, generic over the runtime so the headless test
/// (`dev_spawn_test`, Tauri's mock runtime, no window) builds the same app the dev run does.
pub fn with_plugins<R: Runtime>(builder: Builder<R>) -> Builder<R> {
  builder
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_opener::init())
    .plugin(tauri_plugin_process::init())
}

/// The compiled-in configuration and capabilities, for any runtime. One expansion of
/// `generate_context!` per crate (it embeds the Info.plist once), shared with the test.
pub fn context<R: Runtime>() -> tauri::Context<R> {
  tauri::generate_context!()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  with_plugins(tauri::Builder::default())
    .setup(|app| {
      // The updater only where it is configured: the beta build (tauri.beta.conf.json
      // carries plugins.updater). The dev run has no updater config and none is loaded.
      #[cfg(desktop)]
      if app.config().plugins.0.contains_key("updater") {
        app.handle().plugin(tauri_plugin_updater::Builder::new().build())?;
      }
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(context())
    .expect("error while running tauri application");
}

#[cfg(all(test, unix))]
mod dev_spawn_test;
