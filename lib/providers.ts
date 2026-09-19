import { env } from 'cloudflare:workers';
import { companies, type Company, type Quarter } from './data';
export interface IPOProvider { getCompanies():Promise<Company[]> }
export interface ResultsProvider { getQuarterlyHistory(id:string):Promise<Quarter[]> }
export interface PriceProvider { getPrice(id:string):Promise<number|null> }
export interface GMPProvider { getGmp(id:string):Promise<number|null> }
export async function getRecords(){if(!env.DB)throw new Error('Database unavailable');return (await env.DB.prepare('SELECT * FROM records ORDER BY updated_at DESC').all<{id:string;kind:string;company_id:string;payload:string;source_url:string;updated_at:string;updated_by:string}>()).results;}
export const sampleProvider:IPOProvider={async getCompanies(){return structuredClone(companies)}};
// Provider boundary: replace the sample adapter when verified feeds are configured.
export const ipoProvider:IPOProvider={async getCompanies(){const list=await sampleProvider.getCompanies();const records=await getRecords();for(const record of records){const company=list.find(c=>c.id===record.company_id);if(!company)continue;const payload=JSON.parse(record.payload);if(record.kind==='gmp')company.gmp=payload.gmp;else if(record.kind==='quarter'){const existing=company.quarters.findIndex(q=>q.period===payload.period);if(existing>=0)company.quarters[existing]=payload;else company.quarters.push(payload);company.quarters.sort((a,b)=>Number(a.period.slice(-2))-Number(b.period.slice(-2))||a.period.localeCompare(b.period));}}return list}};
export const resultsProvider:ResultsProvider={async getQuarterlyHistory(id){return (await ipoProvider.getCompanies()).find(c=>c.id===id)?.quarters??[]}};
export const priceProvider:PriceProvider={async getPrice(id){return (await ipoProvider.getCompanies()).find(c=>c.id===id)?.cmp??null}};
export const gmpProvider:GMPProvider={async getGmp(id){return (await ipoProvider.getCompanies()).find(c=>c.id===id)?.gmp??null}};
