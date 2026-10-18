export default function Page() {
  return (
    <main className="page">
      <div className="eyebrow">Workspace</div>
      <h1>Settings</h1>
      <section className="panel settings-note">
        <h2>Settings will be available when the service is connected</h2>
        <p>
          Site targets and provider switches are managed by the network service.
          This dashboard does not save configuration yet.
        </p>
        <p className="muted">No configuration changes can be made here.</p>
      </section>
    </main>
  );
}
