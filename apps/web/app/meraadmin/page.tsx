import Console from './console';
export const metadata = { title: 'Maintenance console', robots: { index: false, follow: false } };
export default function Admin() {
  return (
    <main>
      <div className="page-heading">
        <div>
          <p className="eyebrow">PRIVATE MAINTENANCE</p>
          <h1>
            MeraAdmin<span>.</span>
          </h1>
          <p>Keep the research accurate. Give readers a thoughtful perspective.</p>
        </div>
      </div>
      <Console />
    </main>
  );
}
