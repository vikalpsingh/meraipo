export type Quarter={period:string;revenue:number;ebitda:number;pat:number;eps:number;debt:number;cashFlow:number};
export type Company={id:string;name:string;code:string;sector:string;status:'Open'|'Upcoming'|'Listed';dates:string;issue:number;listing:number|null;cmp:number|null;lot:number;size:number;subscription:number|null;gmp:number;quarters:Quarter[]};
const quarters=(factor:number):Quarter[]=>[['Q1 FY26',680,68,31],['Q2 FY26',735,81,36],['Q3 FY26',812,99,45],['Q4 FY26',905,118,58]].map(([period,revenue,ebitda,pat],i)=>({period:String(period),revenue:Number(revenue)*factor,ebitda:Number(ebitda)*factor,pat:Number(pat)*factor,eps:Number((Number(pat)*factor/20).toFixed(2)),debt:200-i*12,cashFlow:35+i*8}));
export const companies:Company[]=[
{id:'aarya-energy',name:'Aarya Energy',code:'AARYA',sector:'Renewable energy',status:'Open',dates:'21 – 24 Sep 2026',issue:285,listing:null,cmp:null,lot:50,size:1240,subscription:4.82,gmp:42,quarters:[]},
{id:'nimbus-logistics',name:'Nimbus Logistics',code:'NIMBUS',sector:'Logistics & supply chain',status:'Open',dates:'22 – 25 Sep 2026',issue:164,listing:null,cmp:null,lot:90,size:860,subscription:2.16,gmp:18,quarters:[]},
{id:'terra-health',name:'Terra Health',code:'TERRA',sector:'Healthcare services',status:'Upcoming',dates:'28 – 30 Sep 2026',issue:420,listing:null,cmp:null,lot:35,size:1850,subscription:null,gmp:0,quarters:[]},
{id:'prava-tech',name:'Prava Technologies',code:'PRAVA',sector:'Enterprise technology',status:'Listed',dates:'Listed 18 Mar 2025',issue:240,listing:288,cmp:386,lot:60,size:920,subscription:18.4,gmp:0,quarters:quarters(1)},
{id:'vedant-consumer',name:'Vedant Consumer',code:'VEDANT',sector:'Consumer products',status:'Listed',dates:'Listed 12 Feb 2025',issue:185,listing:201,cmp:228,lot:80,size:670,subscription:8.6,gmp:0,quarters:quarters(.6)},
{id:'orion-components',name:'Orion Components',code:'ORION',sector:'Advanced manufacturing',status:'Listed',dates:'Listed 08 Jan 2025',issue:320,listing:304,cmp:292,lot:45,size:1080,subscription:3.2,gmp:0,quarters:quarters(.8).map((q,i)=>({...q,pat:40-i*3}))}];
export const money=(v:number)=>'₹'+v.toLocaleString('en-IN',{maximumFractionDigits:2});
export const change=(current:number,baseline:number)=>(current/baseline-1)*100;
export const percent=(v:number)=>(v>=0?'+':'')+v.toFixed(1)+'%';
