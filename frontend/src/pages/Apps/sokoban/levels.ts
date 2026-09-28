import maps from './levels.json';
import { parseLevel, type Level } from './engine';

export const levels = maps as Level[];
export const boards = Object.fromEntries(levels.map(level => [level.id, parseLevel(level)]));
