import { redirect } from 'next/navigation';
export default async function Legacy({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect('/ipo/' + id);
}
