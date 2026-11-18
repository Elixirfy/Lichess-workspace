// Vosk derives its language model from the frequency of phrases in this list.
export function balanceGrammar(phrases: string[]): string[] {
  const unique = [...new Set(phrases)];
  const maxPhrases = 8192;
  if (unique.length > maxPhrases) return unique;
  const groups = new Map<string, string[]>();
  for (const phrase of unique) {
    const ending = phrase.split(' ').slice(-2).join(' ');
    const group = groups.get(ending);
    if (group) group.push(phrase);
    else groups.set(ending, [phrase]);
  }
  if (groups.size < 2) return unique;

  // Notation aliases must not count as evidence that one spoken destination is
  // more likely than another. Equalize the mass of terminal word pairs, keeping
  // complete phrases so sentence-end probabilities remain in the right places.
  const limit = Math.floor(maxPhrases / groups.size);
  let mass = 1;
  for (const group of groups.values()) {
    let a = mass;
    let b = group.length;
    while (b) [a, b] = [b, a % b];
    mass = Math.min((mass / a) * group.length, limit);
    if (mass === limit) break;
  }
  const weighted: string[] = [];
  for (const group of groups.values()) {
    const repeat = Math.max(1, Math.round(mass / group.length));
    if (weighted.length + group.length * repeat > maxPhrases) return unique;
    for (const phrase of group) for (let i = 0; i < repeat; i++) weighted.push(phrase);
  }
  return weighted;
}
