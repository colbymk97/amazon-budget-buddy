export function BabySisterPage() {
  return (
    <section
      className="grid min-h-[70vh] place-items-center gap-4 rounded-xl bg-linear-to-br from-amber-50 via-pink-50 to-cyan-50 p-8"
      aria-label="Baby Sister smile page"
    >
      <div className="text-3xl font-extrabold tracking-[0.08em] text-slate-700">BABY SISTER</div>
      <div className="text-[clamp(8rem,22vw,18rem)] leading-none font-extrabold text-slate-900" role="img" aria-label="big smile">
        :)
      </div>
    </section>
  );
}
