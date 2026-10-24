const MANUAL_URL = "https://cdn.rekordbox.com/files/20260409170202/rekordbox7.2.14_manual_JA.pdf#page=20";

export function RekordboxImportGuide({ xmlPath, existing = false }: { xmlPath: string; existing?: boolean }) {
  return <section className="xml-import-guide" aria-label="rekordboxへの取り込み手順">
    <h3>rekordboxへの取り込み手順</h3>
    <label htmlFor="exported-xml-path">指定するXMLファイル（クリックでパスを全選択）</label>
    <input id="exported-xml-path" className="mono" readOnly value={xmlPath} onFocus={(event) => event.currentTarget.select()} />
    <ol>
      <li>rekordboxの「ファイル → 環境設定」を開きます。画面上部の歯車からも開けます。</li>
      <li>「表示 → レイアウト」の「メディアブラウザ」で「rekordbox xml」にチェックを入れます。</li>
      <li>「詳細 → データベース」の「rekordbox xml」で、「インポートされているライブラリ」に上のXMLファイルを指定します。フォルダではなく <code>rekordbox.xml</code> を選んでください。</li>
      <li>環境設定を閉じ、左側のメディアブラウザで「rekordbox xml」を開き、ツリービューの「すべての楽曲」を選びます。一覧が更新されない場合は、rekordbox xmlの更新ボタンを押します。</li>
      <li>対象曲を選び、画面上部の「トラック → コレクションにインポート」を選びます。</li>
      {existing && <li>「既に含まれています。情報を読み込みますか？」と表示されたら、確認した元曲であることを確かめて「はい」を選びます。デッキの曲を読み込み直し、MEMORY／HOT CUEを確認してください。</li>}
    </ol>
    <p className="field-help">{existing ? "このXMLは元の音源を参照します。対象曲のCueを更新すると、その曲を使っているプレイリストでも同じCueを利用できます。取り込み前にrekordboxで編集した場合は、最新XMLで追加内容を確認し直してください。" : "このXMLは書き出しフォルダ内の複製音源を参照します。コレクションへ取り込むと、複製した曲が登録されます。"}</p>
    <a href={MANUAL_URL} target="_blank" rel="noreferrer">公式マニュアル：rekordbox.xmlを使う（20ページ）</a>
  </section>;
}
