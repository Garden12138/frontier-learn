import { arxivAdapter } from './arxiv';
import { huggingfaceAdapter } from './huggingface';

export type { PageSnapshot, PageBlock, Extraction } from './types';
export function adapterFor(url: string) { return arxivAdapter(url) ?? huggingfaceAdapter(url); }
