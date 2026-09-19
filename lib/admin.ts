import {getChatGPTUser} from '@/app/chatgpt-auth';
export async function isAdmin(){const user=await getChatGPTUser();return user?.email.toLowerCase()==='vikalp.singh@gmail.com'?user:null;}
