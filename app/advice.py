"""Concreet advies bij een signaal: wat zou je beter kunnen doen dan nu
instappen, gebaseerd op dezelfde vier factoren als het vertrouwen-oordeel.
Geen aparte black box, gewoon de praktische vertaling van de factoren die
al getoond worden."""


def build_advice(signal: dict) -> str:
    # technical_confirmed betekent voor een swing-signaal iets anders (het
    # bewaakte niveau is bevestigd, geen 3-van-4-toets), dus het
    # day-trading-advies eronder klopt er niet voor.
    if signal.get("trade_type") == "swing":
        return (
            "Geen automatisch advies voor een bewaakt niveau: beoordeel de "
            "daily- en 4-uur-factoren in de melding zelf, dit is geen "
            "3-van-4-toets zoals bij day trading."
        )

    is_pattern = signal.get("trade_type") == "patroon"
    pattern_name = signal.get("pattern_name") or "onbekend patroon"
    factor_pct = signal.get("pass_pct")

    # Een patroon-signaal heeft, sinds de factor-toetsing ook op patronen
    # draait (zie compute_full_confirmation), een echte breakdown in
    # signal["reason"] i.p.v. de vroegere platte "Patroon: ...". Boven de
    # helft van de factoren klopt -> citeer die breakdown i.p.v. de
    # generieke "alle vier factoren"-tekst hieronder, die alleen voor
    # dagtrading klopt (technical_confirmed staat voor patroon altijd op
    # 1, zegt dus niets over de factoren zelf).
    if is_pattern and factor_pct is not None and factor_pct >= 50:
        return (
            f"Patroon ({pattern_name}) wordt ondersteund door de factoren: "
            f"{signal.get('reason') or 'geen details beschikbaar'}."
        )

    if not is_pattern and signal.get("technical_confirmed"):
        return "Alle vier factoren kloppen, dit is volgens de regels een directe instap."

    direction = (signal.get("direction") or "").lower()
    rsi = signal.get("rsi")
    ema9 = signal.get("ema9")
    ema21 = signal.get("ema21")
    macd = signal.get("macd")
    macd_signal = signal.get("macd_signal")
    volume_ratio = signal.get("volume_ratio")

    tips = []

    if ema9 is not None and ema21 is not None:
        trend_up = ema9 > ema21
        if direction == "long" and not trend_up:
            tips.append(f"wacht tot EMA9 boven EMA21 komt (nu {ema9:.4f} tegen {ema21:.4f})")
        elif direction == "short" and trend_up:
            tips.append(f"wacht tot EMA9 onder EMA21 komt (nu {ema9:.4f} tegen {ema21:.4f})")

    if macd is not None and macd_signal is not None:
        momentum_up = macd > macd_signal
        if direction == "long" and not momentum_up:
            tips.append("wacht tot de MACD-lijn boven de signaallijn kruist voor opwaarts momentum")
        elif direction == "short" and momentum_up:
            tips.append("wacht tot de MACD-lijn onder de signaallijn kruist voor neerwaarts momentum")

    if rsi is not None and ema21 is not None:
        if direction == "long" and rsi >= 75:
            tips.append(f"RSI staat op {rsi:.0f}, oververhit: wacht op een terugval richting EMA21 rond {ema21:.4f} voor een gunstiger instapmoment")
        elif direction == "short" and rsi <= 25:
            tips.append(f"RSI staat op {rsi:.0f}, oversold: wacht op een opleving richting EMA21 rond {ema21:.4f} voor een gunstiger instapmoment")

    if volume_ratio is not None and volume_ratio < 1.0:
        tips.append(f"volume ligt op {volume_ratio:.2f}x het gemiddelde, nog niet overtuigend: wacht op een sterkere beweging")

    if not tips:
        if is_pattern:
            tips.append(f"niet alle factoren ondersteunen dit patroon ({pattern_name}) nog, beoordeel de nek/lijn zelf voor je instapt")
        else:
            tips.append("niet alle vier factoren kloppen, wacht op een duidelijkere bevestiging voor je instapt")

    return " Ook: ".join(tips) if len(tips) > 1 else tips[0]
