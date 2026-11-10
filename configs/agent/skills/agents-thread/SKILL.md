---
name: agents-thread
description: agents-worker の古い名前。名前を変える前に起動した worker や、古い依頼の先頭の /agents-thread のために残している。読み込んだら agents-worker に従う。
disable-model-invocation: true
---

# agents-worker の古い名前

このスキルは `agents-worker` に名前を変えた。読み込んだら、Skill ツールで `agents-worker` を読み込み、その決まりに従って、このスキルのあとに書かれた依頼を進める。

- 窓口は、新しく起動する worker の依頼の先頭に `/agents-worker` を付ける。この古い名前は、動いている worker がすべて片付いたら消す。
