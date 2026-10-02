/* Chord symbol -> pitch classes + default piano voicing. Shared by the page and the measuring script. */
const CT = (() => {
  const LET = {C:0,D:2,E:4,F:5,G:7,A:9,B:11};
  const pcOf = s => { let p = LET[s[0]]; for (const a of s.slice(1)) p += a==='#'?1:a==='b'?-1:0; return (p+120)%12; };
  // returns {root, bass, tones:[semitones above root], pcs:[pitch classes]} or null for N.C./unparsable
  function parse(sym){
    sym = String(sym||'').replace(/[?\s]/g,'').replace(/♭/g,'b').replace(/♯/g,'#');
    const m = /^([A-G][#b]?)(.*?)(?:\/([A-G][#b]?))?$/.exec(sym); if (!m) return null;
    const root = pcOf(m[1]); const bass = m[3] ? pcOf(m[3]) : root; let q = m[2];
    let third = 4, fifth = 7, sev = null; const ext = new Set();
    if (/^(maj|M|Δ)/.test(q)){ if (/^(maj|M|Δ)(7|9|11|13)/.test(q)) sev = 11; q = q.replace(/^(maj|M|Δ)/,''); }
    else if (/^(m|min|-)(?!aj)/.test(q)){ third = 3; q = q.replace(/^(min|m|-)/,''); if (/^(maj|M)7/.test(q)){ sev = 11; q = q.replace(/^(maj|M)/,''); } }
    else if (/^(dim|°|o)/.test(q)){ third = 3; fifth = 6; q = q.replace(/^(dim|°|o)/,''); if (/^7/.test(q)){ sev = 9; q = q.slice(1); } }
    else if (/^(aug|\+)/.test(q)){ fifth = 8; q = q.replace(/^(aug|\+)/,''); }
    if (/ø/.test(q)){ third = 3; fifth = 6; sev = 10; q = q.replace('ø',''); }
    if (/7b5/.test(q) && third === 3){ fifth = 6; }
    if (/sus2/.test(q)) third = 2; else if (/sus4?/.test(q)) third = 5;
    q = q.replace(/sus[24]?/,'');
    const six9 = /6\/9|69/.test(q); if (six9){ ext.add(9); ext.add(2); q = q.replace(/6\/9|69/,''); }
    if (/add(9|2)/.test(q)){ ext.add(2); q = q.replace(/add(9|2)/,''); }
    if (/add11|add4/.test(q)){ ext.add(5); q = q.replace(/add(11|4)/,''); }
    if (/(^|[^b#\d])6/.test(q)){ ext.add(9); }
    if (sev == null && /(^|[^b#\d])(7|9|11|13)/.test(q)) sev = 10;
    if (/(^|[^b#\d1])9/.test(q)) ext.add(2);
    if (/(^|[^b#\d])11/.test(q)){ ext.add(2); ext.add(5); }
    if (/(^|[^b#\d])13/.test(q)){ ext.add(2); ext.add(9); }
    if (/b9/.test(q)) ext.add(1); if (/#9/.test(q)) ext.add(3); if (/#11/.test(q)) ext.add(6); if (/b13/.test(q)) ext.add(8);
    if (/b5/.test(q) && third !== 3) fifth = 6; if (/#5/.test(q)) fifth = 8;
    const tones = [0, third, fifth]; if (sev != null) tones.push(sev); ext.forEach(e => tones.push(e));
    if (/no3/.test(q)) tones.splice(tones.indexOf(third),1);
    if (/no5|omit5/.test(q)) tones.splice(tones.indexOf(fifth),1);
    const uniq = [...new Set(tones)];
    return {root, bass, tones: uniq, pcs: [...new Set(uniq.map(t => (root+t)%12))]};
  }
  // simple default voicing: bass in C2–B2, close right hand in A3–G#4
  function defaultVoicing(sym){
    const p = parse(sym); if (!p) return null;
    let rh = p.pcs.filter(pc => pc !== p.bass); if (rh.length < 3) rh = p.pcs.slice();
    const notes = rh.map(pc => 57 + ((pc - 57) % 12 + 12) % 12).sort((a,b)=>a-b);
    if (notes.length > 1 && notes[1] - notes[0] === 1){ notes.push(notes.shift() + 12); }
    return [36 + p.bass, ...notes];
  }
  return {parse, defaultVoicing, pcOf};
})();
if (typeof module !== 'undefined') module.exports = CT;
