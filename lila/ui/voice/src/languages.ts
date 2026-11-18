export const supportedLangs: [string, string][] = [
  ['en', 'English'],
  ['fr', 'Français'],
  ['pl', 'Polski'],
  ['vi', 'Tiếng Việt (thử nghiệm)'],
];

if (site.debug)
  supportedLangs.push(
    ['de', 'Deutsch'],
    ['tr', 'Türkçe'],
    ['ru', 'Русский'],
    ['it', 'Italiano'],
    ['sv', 'Svenska'],
  );
