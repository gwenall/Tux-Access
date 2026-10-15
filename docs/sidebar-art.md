# Sidebar artwork

Credit: fourteen musical Tux illustrations supplied by the user. The original square PNGs are copied unchanged, retaining their transparency; source and bundled file SHA-256 hashes were compared after copying. All fourteen have distinct hashes, so duplicate artwork does not receive extra weight in the random pool.

| Bundled file | Original filename |
| --- | --- |
| `assets/tux/tux-flying-v-guitar-headphones.png` | `ChatGPT Image Oct 15, 2026, 10_21_55 AM-1.png` |
| `assets/tux/tux-dj-turntables-headphones.png` | `ChatGPT Image Oct 15, 2026, 10_21_56 AM-2.png` |
| `assets/tux/tux-violin-bow-tie.png` | `ChatGPT Image Oct 15, 2026, 10_21_57 AM-3.png` |
| `assets/tux/tux-keyboard-player.png` | `ChatGPT Image Oct 15, 2026, 10_21_58 AM-4.png` |
| `assets/tux/tux-saxophone-sunglasses.png` | `ChatGPT Image Oct 15, 2026, 10_21_59 AM-5.png` |
| `assets/tux/tux-drum-kit.png` | `ChatGPT Image Oct 15, 2026, 10_22_00 AM-6.png` |
| `assets/tux/tux-flying-v-guitar.png` | `ChatGPT Image Oct 15, 2026, 10_22_01 AM-7.png` |
| `assets/tux/tux-home-music-studio.png` | `ChatGPT Image Oct 15, 2026, 10_22_01 AM-8.png` |
| `assets/tux/tux-acoustic-guitar-headphones.png` | `ChatGPT Image Oct 15, 2026, 02_16_05 PM-1.png` |
| `assets/tux/tux-flute-headphones.png` | `ChatGPT Image Oct 15, 2026, 02_16_06 PM-2.png` |
| `assets/tux/tux-clarinet-headphones.png` | `ChatGPT Image Oct 15, 2026, 02_16_07 PM-3.png` |
| `assets/tux/tux-cello-headphones.png` | `ChatGPT Image Oct 15, 2026, 02_16_08 PM-4.png` |
| `assets/tux/tux-bass-guitar-headphones.png` | `ChatGPT Image Oct 15, 2026, 02_16_09 PM-5.png` |
| `assets/tux/tux-singer-microphone.png` | `ChatGPT Image Oct 15, 2026, 02_16_12 PM-6.png` |

One random image is selected per application process and stays fixed through navigation, filtering, Settings and account changes. A best-effort cache stores only the previous bundled filename at `$XDG_CACHE_HOME/native-access-linux/sidebar-art.txt` (normally `~/.cache/native-access-linux/sidebar-art.txt`) to avoid an immediate repeat. Cache failure never blocks startup. Missing assets leave the sidebar space empty.

The former filenames `tux-01.png` through `tux-08.png` map in order to the first eight descriptive filenames above. Startup translates an old cached name before excluding the previous picture, preserving the no-repeat behavior across this rename without changing a running window's artwork. The source PNG bytes are unchanged.

`sidebar_art.py` locates source assets relative to its module, then falls back to `sys.prefix/share/native-access-linux/assets/tux`. Qt scales with `KeepAspectRatio` and smooth rendering, preserving alpha. The illustration occupies only the former stretch space, shrinks on shorter windows and disappears when that space becomes too small; navigation and account controls retain priority.
