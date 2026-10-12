export default function App() {
  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-4 p-4">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Live Football Analytics</h1>
      </header>
      <main className="grid flex-1 gap-4 lg:grid-cols-[1fr_22rem]">
        <section aria-label="Charts" className="rounded-lg bg-slate-900 p-4" />
        <aside aria-label="Alerts" className="rounded-lg bg-slate-900 p-4" />
      </main>
    </div>
  )
}
