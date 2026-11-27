Beta build @TAG@. Which file to download, and the full steps: [TESTERS.md](https://github.com/@REPO@/blob/@TAG@/TESTERS.md).

@WHATS_NEW@
## Install

| Your computer | File |
|---|---|
| Mac with Apple silicon (M1, M2, M3, M4…) | `Zugzwang_<version>_aarch64.dmg` |
| Mac with an Intel processor | `Zugzwang_<version>_x64.dmg` |
| Windows 10 or 11 (64-bit) | `Zugzwang_<version>_x64-setup.exe` |

**Mac: open it the first time with System Settings → Privacy & Security → Open Anyway.** Zugzwang isn't notarized by Apple yet. This is a one-time step; updates install normally afterwards.

1. Open the `.dmg`, drag **Zugzwang** into **Applications** and open it. macOS says it cannot verify the developer:
   click **Done**, not *Move to Bin*.
2. **System Settings → Privacy & Security**: scroll to the message about Zugzwang, click **Open Anyway**, confirm with
   your password, and open Zugzwang again.

Only if there is no **Open Anyway** (or macOS says the app "is damaged"), run this once in Terminal, then open
Zugzwang again:

```
xattr -dr com.apple.quarantine /Applications/Zugzwang.app
```

**Windows:** if "Windows protected your PC" appears, click **More info**, then **Run anyway**.

Source: the tag @TAG@.
