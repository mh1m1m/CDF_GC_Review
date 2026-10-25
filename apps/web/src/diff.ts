/** Deterministic token-level difference display (display-only, never evidence authority). */
export type DiffToken = { text: string; op: "same" | "added" | "removed" };
function tokenize(s: string): string[] {
  return s.match(/\s+|[^\s]+/gu) || [];
}
export function diffTokens(oldText: string, newText: string): { old: DiffToken[]; revised: DiffToken[]; bounded: boolean } {
  const a = tokenize(oldText), b = tokenize(newText);
  // Bound quadratic matching work; large comments use simple whole-text display.
  if (a.length > 600 || b.length > 600) {
    return { old: [{ text: oldText, op: "removed" }], revised: [{ text: newText, op: "added" }], bounded: true };
  }
  const dp = Array.from({length: a.length+1},()=>new Uint16Array(b.length+1));
  for(let i=a.length-1;i>=0;i--) for(let j=b.length-1;j>=0;j--)
    dp[i][j] = a[i] === b[j] ? dp[i+1][j+1]+1 : Math.max(dp[i+1][j], dp[i][j+1]);
  const old:DiffToken[]=[],revised:DiffToken[]=[];
  let i=0,j=0;
  while(i<a.length || j<b.length){
    if(i<a.length && j<b.length && a[i]===b[j]){
      old.push({text:a[i],op:"same"}); revised.push({text:b[j],op:"same"});i++;j++;
    }else if(j<b.length && (i===a.length||dp[i][j+1]>=dp[i+1][j])){
      revised.push({text:b[j],op:"added"});j++;
    }else{
      old.push({text:a[i],op:"removed"});i++;
    }
  }
  return {old,revised,bounded:false};
}
