export default function LanguagePicker({ languages, value, onChange }) {
  return (
    <div className="langpick">
      <label htmlFor="language">Explain in</label>
      <select id="language" value={value} onChange={(e) => onChange(e.target.value)}>
        {languages.map((l) => (
          <option key={l.code} value={l.code}>{l.native_name === l.name ? l.name : `${l.native_name} (${l.name})`}</option>
        ))}
      </select>
    </div>
  );
}
