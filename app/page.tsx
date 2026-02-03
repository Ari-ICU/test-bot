export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 bg-background text-foreground">
      <div className="max-w-2xl text-center space-y-6">
        <h1 className="text-4xl font-bold tracking-tight">Trading Bot</h1>
        <p className="text-lg text-muted-foreground">
          This is a Python-based trading bot project. The bot includes features for forex and crypto trading with various strategies.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 mt-8">
          <div className="p-4 border rounded-lg">
            <h2 className="font-semibold mb-2">Strategies</h2>
            <p className="text-sm text-muted-foreground">
              Scalping, Trend Following, Breakout, ICT Silver Bullet, and more
            </p>
          </div>
          <div className="p-4 border rounded-lg">
            <h2 className="font-semibold mb-2">Features</h2>
            <p className="text-sm text-muted-foreground">
              AI-powered predictions, Risk management, Telegram alerts
            </p>
          </div>
        </div>
      </div>
    </main>
  )
}
