import {getChatGPTUser,chatGPTSignInPath} from '@/app/chatgpt-auth';
import {isAdmin} from '@/lib/admin';
import AdminForm from './form';
export const dynamic='force-dynamic';
export const metadata={title:'MeraIPO — Maintenance',robots:{index:false,follow:false}};
export default async function Admin(){const user=await getChatGPTUser();if(!user)return <main className="empty"><h1>Maintenance console</h1><p>Administrator access is required.</p><a className="primary-button" href={chatGPTSignInPath('/meraadmin')} target="_top">Sign in with ChatGPT</a></main>;if(!await isAdmin())return <main className="empty"><h1>Access restricted</h1><p>This account does not have administrator access.</p><a className="outline-button" href="/signout-with-chatgpt?return_to=/meraadmin">Use another account</a></main>;return <main><div className="page-heading"><div><p className="eyebrow">PRIVATE MAINTENANCE</p><h1>MeraAdmin<span>.</span></h1><p>Update GMP and preserve quarterly business records.</p></div><span className="badge">{user.email}</span></div><AdminForm/></main>}
