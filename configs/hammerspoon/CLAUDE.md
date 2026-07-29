# Hammerspoon

YAMLで宣言したwindow layoutを`layout_manager.lua`から適用する。

## 変更時の契約

- 座標は画面に対する`0.0`〜`1.0`の正規化値として扱う。
- `instance`を省略した同一appのwindowはcycle対象にする。
- layout適用、window探索、hotkey登録の責務をmodule間で混ぜない。
- `layouts.yml`は個人設定、`layouts.yml.example`は共有可能な例として扱う。

schema、座標例、variant、hotkey追加方法が必要なときだけ
[`references/layouts.md`](references/layouts.md)を読む。
