function md-gdocs --description 'Markdown を Google Docs の「Markdown から貼り付け」向けに直してクリップボードに入れる'
    # 箇条書きの - を * に直す。ファイルを省くと標準入力を読む。--stdout で標準出力に出す
    python3 ~/.claude/skills/report-writing/scripts/md_to_gdocs.py $argv
end
