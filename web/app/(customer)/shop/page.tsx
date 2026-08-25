import Link from "next/link";

export default function ShopPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_right,_#d8e6bf,_transparent_34%),linear-gradient(135deg,_#f4f0e7_0%,_#f4f0e7_70%,_#e6dcc9_100%)] px-6 py-8 sm:px-12">
      <nav className="mx-auto flex max-w-6xl items-center justify-between border-b border-[#17211f]/15 pb-5 text-sm font-semibold uppercase tracking-[0.18em]">
        <span>CartPilot / Shop</span>
        <Link className="text-[#1f5b46] underline underline-offset-4" href="/dashboard">Merchant view</Link>
      </nav>
      <section className="mx-auto grid max-w-6xl gap-10 py-20 lg:grid-cols-[1.3fr_0.7fr]">
        <div>
          <p className="mb-5 font-mono text-xs uppercase tracking-[0.22em] text-[#e95b2f]">Conversational commerce</p>
          <h1 className="max-w-3xl text-5xl font-black leading-[0.94] tracking-[-0.06em] sm:text-7xl">Find the run that feels like yours.</h1>
          <p className="mt-7 max-w-xl text-lg leading-8 text-[#17211f]/70">Tell CartPilot about distance, terrain, fit and budget. The shopping agent will show its work before anything enters your cart.</p>
          <div className="mt-10 rounded-3xl border border-[#17211f]/15 bg-[#fffdf8]/80 p-6 shadow-[10px_10px_0_#1f5b46]">
            <p className="font-mono text-xs uppercase tracking-[0.16em] text-[#1f5b46]">Try the demo prompt</p>
            <p className="mt-3 text-xl font-semibold">“I need running shoes under ₹5,000 for daily 5 km runs and I have flat feet.”</p>
            <button className="mt-6 rounded-full bg-[#17211f] px-5 py-3 text-sm font-bold text-white" type="button" disabled>Chat arrives in T-008</button>
          </div>
        </div>
        <aside className="self-end rounded-[2rem] bg-[#1f5b46] p-8 text-[#f4f0e7] shadow-[12px_12px_0_#e95b2f]">
          <p className="font-mono text-xs uppercase tracking-[0.16em] text-[#d8e6bf]">Foundation ready</p>
          <h2 className="mt-4 text-3xl font-black tracking-[-0.04em]">A real catalog, guarded checkout.</h2>
          <ul className="mt-7 space-y-3 text-sm leading-6 text-[#f4f0e7]/80">
            <li>• 217 size-specific demo SKUs</li>
            <li>• Server-owned inventory and prices</li>
            <li>• Confirmation before payment</li>
          </ul>
        </aside>
      </section>
    </main>
  );
}
