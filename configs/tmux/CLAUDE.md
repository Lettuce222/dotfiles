# tmux

## prefix 変更時の追従

tmux の prefix キー（`set -g prefix ...`）を変更したら、`configs/karabiner/karabiner.json` の IME 連動ルールのキーコードも揃える。

**理由**: ターミナルで tmux prefix を押したときに日本語 IME を OFF にする karabiner ルールがあり、そこで `from.key_code` と `to[1].key_code` に prefix キーが hard-code されている。tmux 側だけ変えると cross-file で静かに壊れる。

**追従箇所**: `configs/karabiner/karabiner.json` 内、description が「ターミナルで Ctrl+... (tmux prefix) を押したら日本語IMEをOFFにしてから送出する」のルール。`from.key_code`、`to[1].key_code`、description の 3 箇所を更新する。
