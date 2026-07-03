---
type: area
aliases: [ホーム, トップ]
tags: [moc]
updated: {{date:YYYY-MM-DD}}
---

# HOME

仕事の全体観の入口。各分野の MOC へここから辿る。

## 分野（MOC）

必要になったら、ここに `[[MOC-...]]` を追加する。

## 進行中のイニシアチブ

```dataview
LIST FROM #initiative WHERE status = "active" SORT updated DESC
```
> Dataview プラグイン未導入なら、ここに手動で `[[initiative-...]]` を並べる。

## 使い方メモ

- 新しい分野を作ったらここに `[[MOC-...]]` を足す。
- 「全体観を掴みたい」ときはまず該当 MOC を開く。
