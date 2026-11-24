// Map color themes. Same hue order in both so "Bolt is blue" holds across themes;
// light mode uses deeper tones so points keep contrast on a pale background.
export type ThemeName = 'dark' | 'light';

export interface MapTheme {
  name: ThemeName;
  bg: string;
  palette: string[];
  muted: string; // parts with no duplicate
  gt: Record<string, string>;
  savLo: string;
  savHi: string;
  focus: string; // focus / group overlay
  selected: string; // the clicked point
  dupLine: string;
  otherLine: string;
  plant: Record<string, string>;
  plantFallback: string;
  lookalike: string;
  threshold: string;
  ghost: number; // cloud opacity in close-up
}

export const DARK: MapTheme = {
  name: 'dark',
  bg: '#0d1520',
  palette: ['#ff6b4a', '#4cc3ff', '#ffc94a', '#7ee081', '#c08bff', '#ff8fc7', '#5ad1c8',
    '#f2994a', '#9db4ff', '#e0e36b', '#ff9e7a', '#6fe3ff'],
  muted: '#34414f',
  gt: { duplicate: '#4ade80', base: '#4cc3ff', hard_negative: '#ff6b4a', near_miss: '#ffc94a' },
  savLo: '#2a6f97',
  savHi: '#ff6b4a',
  focus: '#ffb547',
  selected: '#ffffff',
  dupLine: '#4ade80',
  otherLine: '#8aa0b4',
  plant: { TR0: '#4cc3ff', TR1: '#5ad1c8', HV0: '#ffc94a', HV1: '#ff8fc7' },
  plantFallback: '#c08bff',
  lookalike: '#6b7f93',
  threshold: '#4ade80',
  ghost: 0.07,
};

export const LIGHT: MapTheme = {
  name: 'light',
  bg: '#f7f9fb',
  palette: ['#e5533d', '#1c8ad6', '#d99a00', '#2f9e44', '#7c4ddb', '#d6409f', '#0f9d8f',
    '#e8770e', '#4c6ef5', '#8a8f00', '#f06c4f', '#0b9bd1'],
  muted: '#cfd7df',
  gt: { duplicate: '#2f9e44', base: '#1c8ad6', hard_negative: '#e5533d', near_miss: '#d99a00' },
  savLo: '#9cc3dd',
  savHi: '#e5533d',
  focus: '#f08c00',
  selected: '#1b2733',
  dupLine: '#16a34a',
  otherLine: '#8a99a8',
  plant: { TR0: '#1c8ad6', TR1: '#0f9d8f', HV0: '#d99a00', HV1: '#d6409f' },
  plantFallback: '#7c4ddb',
  lookalike: '#9aa8b6',
  threshold: '#16a34a',
  ghost: 0.14,
};

export const THEMES: Record<ThemeName, MapTheme> = { dark: DARK, light: LIGHT };
