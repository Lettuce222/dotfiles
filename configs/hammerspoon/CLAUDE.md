# Hammerspoon Configuration Guide

## Overview

YAMLベースのウィンドウレイアウト管理システム。ホットキーでアプリをタイル配置できる。

## Directory Structure

```
configs/hammerspoon/
├── init.lua              # メインエントリポイント（直接ホットキーも定義）
├── layouts.yml           # レイアウト定義（git管理外、個人設定）
├── layouts.yml.example   # レイアウトのサンプル
├── lib/
│   └── tinyyaml.lua      # YAMLパーサー
└── modules/
    ├── yaml_loader.lua       # YAML読み込み
    ├── layout_manager.lua    # レイアウト適用・ウィンドウサイクル管理
    ├── window_utils.lua      # ウィンドウ操作ユーティリティ
    └── keybinder.lua         # ホットキー登録
```

## Key Files

### layouts.yml

ユーザーのレイアウト定義ファイル。`.gitignore`で除外されている。

```yaml
settings:
  gap: 0                    # ウィンドウ間のギャップ (px)
  launch_wait: 1.5          # アプリ起動後の待機時間 (秒)
  animation_duration: 0     # アニメーション時間 (秒、0で無効)

layouts:
  - name: layout-name
    hotkey:
      mods: alt             # 修飾キー: alt, cmd, ctrl, shift または配列
      key: "1"              # キー
    windows:
      - app: "App Name"     # アプリ名
        position: {x: 0, y: 0, w: 1.0, h: 1.0}  # 位置とサイズ (0.0-1.0)
```

### init.lua

直接定義されているホットキー:
- `Cmd+Alt+Ctrl+R`: 設定リロード
- `Alt+H`: 左のウィンドウにフォーカス移動
- `Alt+L`: 右のウィンドウにフォーカス移動
- `Alt+J`: 次のモニターにフォーカス移動
- `Alt+K`: 前のモニターにフォーカス移動
- `Alt+U`: フォーカスウィンドウを画面左半分に配置
- `Alt+I`: フォーカスウィンドウを画面右半分に配置
- `Alt+O`: フォーカスウィンドウをフルスクリーンに配置

## Layout Configuration

### Position Format

```yaml
position: {x: 0, y: 0, w: 0.5, h: 1.0}
```
- `x`, `y`: 左上の位置 (0.0-1.0)
- `w`, `h`: 幅と高さ (0.0-1.0)

### Common Positions

| 配置 | position |
|------|----------|
| 全画面 | `{x: 0, y: 0, w: 1.0, h: 1.0}` |
| 左半分 | `{x: 0, y: 0, w: 0.5, h: 1.0}` |
| 右半分 | `{x: 0.5, y: 0, w: 0.5, h: 1.0}` |
| 左1/3 | `{x: 0, y: 0, w: 0.33, h: 1.0}` |
| 中央1/3 | `{x: 0.33, y: 0, w: 0.34, h: 1.0}` |
| 右1/3 | `{x: 0.67, y: 0, w: 0.33, h: 1.0}` |

### Modifier Keys

```yaml
# 単一
mods: alt

# 複数
mods: ["alt", "shift"]

# エイリアス定義も可能
modifiers:
  hyper: ["cmd", "alt", "ctrl"]
```

## Features

### Window Cycling

同じアプリが複数ウィンドウ開いている場合、同じホットキーを押すたびに異なるウィンドウの組み合わせにサイクルする。

```yaml
# instance を指定しない場合、自動でサイクル
windows:
  - app: Google Chrome
    position: {x: 0, y: 0, w: 0.5, h: 1.0}
  - app: Google Chrome
    position: {x: 0.5, y: 0, w: 0.5, h: 1.0}
```

### Fixed Instance

特定のウィンドウを固定で使いたい場合は `instance` を指定:

```yaml
windows:
  - app: Google Chrome
    instance: 1  # 常に1番目のウィンドウ
    position: {x: 0, y: 0, w: 0.5, h: 1.0}
```

### Variants (Cyclic Layouts)

同じホットキーで複数のレイアウトを切り替え:

```yaml
- name: focus-mode
  hotkey:
    mods: alt
    key: f
  variants:
    - description: "エディタ全画面"
      windows:
        - app: Code
          position: {x: 0, y: 0, w: 1.0, h: 1.0}
    - description: "ブラウザ全画面"
      windows:
        - app: Google Chrome
          position: {x: 0, y: 0, w: 1.0, h: 1.0}
```

### Auto Window Creation

レイアウトで必要なウィンドウ数が足りない場合、自動で新規ウィンドウを作成する。

## Adding New Features

### New Layout

`layouts.yml` に追加:

```yaml
  - name: new-layout
    hotkey:
      mods: alt
      key: "5"
    windows:
      - app: "App Name"
        position: {x: 0, y: 0, w: 1.0, h: 1.0}
```

### New Global Hotkey

`init.lua` に追加:

```lua
hs.hotkey.bind({"alt"}, "K", function()
    local win = hs.window.focusedWindow()
    if win then
        win:focusWindowNorth(nil, true)
    end
end)
```

## Behavior Notes

- レイアウト適用は現在フォーカスしているモニターのみで動作
- アプリが起動していない場合は自動で起動
- 設定ファイル (layouts.yml) 変更時は自動リロード
- 全てのウィンドウは前面に持ってくる (raise)
