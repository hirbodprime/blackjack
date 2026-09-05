def escape_markdown_v2(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', text)

# ─── Helper: Safe send message with flood control ───
async def safe_send_message(bot, chat_id, text, parse_mode="MarkdownV2", max_retries=10):
    escaped_text = escape_markdown_v2(text)
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=escaped_text, parse_mode=parse_mode)
            return
        except TimedOut:
            retries += 1
            await asyncio.sleep(4)
        except RetryAfter as e:
            await asyncio.sleep(int(e.retry_after) + 1)
            retries += 1
        await asyncio.sleep(0.3)  # flood control
    print("❌ Failed to send message after retries.")

# ─── /horserace: Start a new race ───
async def horserace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    chat_id = update.effective_chat.id
    group_name = update.effective_chat.title or "a group"  # fallback if no title
    language = await sync_to_async(group_language)(chat_id)

    existing_race = await sync_to_async(HorseRace.objects.filter)(chat_id=chat_id, completed=False)
    if await sync_to_async(existing_race.exists)():
        await update.message.reply_text("❗️ A race is already active in this chat!")
        return

    race = await sync_to_async(HorseRace.objects.create)(chat_id=chat_id)

    # Notify users
    notified_users = await sync_to_async(list)(
        UserSettings.objects.filter(notify_race_start=True)
                            .select_related("player")
    )
    print(f"[INFO] Notifying {len(notified_users)} users about horse race start.")

    if update.effective_chat.type in ["group", "supergroup"]:
        for setting in notified_users:
            user_id = setting.player.id
            try:
                # Check if the user is still in the group
                member = await context.bot.get_chat_member(chat_id, user_id)
                if member.status not in ["left", "kicked"]:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=t("group.race_started_notice", language, group_name=group_name)
                    )
            except Exception as e:
                await record_telegram_failure(
                    e, player_id=user_id, chat_id=chat_id,
                    message_type="race_start_notification"
                )

    await update.message.reply_text(t("group.race_started", language))

# ─── /joinrace: Players place their bets ───
async def joinrace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Usage: /joinrace <horse_number> <bet_amount>")
        return

    horse_number = int(args[0])
    bet_amount = int(args[1])

    # Prevent negative or zero bets
    if bet_amount <= 0:
        await update.message.reply_text("❌ Bet amount must be a positive number.")
        return

    if horse_number == 1:
        await update.message.reply_text("❌ You can’t bet on the dealer’s horse!")
        return
    if horse_number < 1:
        await update.message.reply_text("❌ Don't do that!")
        return
    owned_entry = await sync_to_async(OwnedHorse.objects.filter)(horse_number=horse_number)
    owned_entry = await sync_to_async(owned_entry.first)()

    if owned_entry:
        owner_id = await sync_to_async(lambda: owned_entry.user.id)()
        if owner_id != user_id:
            try:
                owner_player = await sync_to_async(Player.objects.get)(id=owner_id)
                owner_name = owner_player.name or "another player"
            except:
                owner_name = "another player"

            await update.message.reply_text(
                f"❌ This horse is already owned by {owner_name} and cannot be bet on by others."
            )
            return


    # First: find the active race
    race = await sync_to_async(HorseRace.objects.filter)(chat_id=chat_id, race_started=False, completed=False)
    race = await sync_to_async(race.first)()
    if not race:
        await update.message.reply_text("❌ No active race! Start one with /horserace")
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    try:
        await place_race_bet_async(
            race_id=race.id,
            player_id=user_id,
            horse_number=horse_number,
            amount=bet_amount,
            username=username,
        )
    except AlreadyBet:
        await update.message.reply_text("❌ You have already placed a bet in this race!")
        return
    except ActiveRaceBet:
        await update.message.reply_text("❌ You already have a bet in another active race!")
        return
    except RaceAlreadyStarted:
        await update.message.reply_text("❌ This race has already started!")
        return
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text("❌ Not enough chips!")
        return
    if bet_amount >= 50000:
        await update_daily_quest_progress(player, "race", "horse50", 1, context)
    if bet_amount >= 200000:
        await update_daily_quest_progress(player, "race", "horse200", 1, context)
    if bet_amount >= 1000000:
        await update_daily_quest_progress(player, "race", "horse1m", 1, context)
    await update_daily_quest_progress(player, "race", "joinhorse", 1, context)
    
    if owned_entry and owned_entry.name:
        label = f"{owned_entry.name} ({horse_number})"
    else:
        label = f"Horse {horse_number}"

    await update.message.reply_text(
        f"✅ Bet placed on {label} for {bet_amount} chips!"
    )


MAX_NAME_LEN     = 20       # max characters per horse name
MAX_MESSAGE_LEN  = 4000     # Telegram’s ~4096-char limit

def is_rtl(text: str) -> bool:
    """
    Return True if any character is in the Arabic/Persian Unicode block.
    """
    for ch in text:
        if '\u0600' <= ch <= '\u06FF' or '\u0750' <= ch <= '\u077F':
            return True
    return False



async def startrace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

    # 1) Ensure the user has a Player profile
    if not await check_player(update, context):
        return

    chat_id = update.effective_chat.id

    # 2) FETCH THE ACTIVE RACE (must not have started yet)
    race_qs = await sync_to_async(HorseRace.objects.filter)(chat_id=chat_id, race_started=False, completed=False)
    race    = await sync_to_async(race_qs.first)()
    if not race:
        await update.message.reply_text("❌ No active race!")
        return

    # 3) GATHER ALL BETS FOR THIS RACE
    bets = await sync_to_async(list)(HorseBet.objects.filter(race=race))
    if not bets:
        await update.message.reply_text("❌ No bets placed!")
        return

    # 4) MARK THE RACE AS “STARTED”
    race.race_started = True
    await sync_to_async(race.save)()

    dealer_horse = 1

    # 5) PICK TWO RANDOM “HOUSE” HORSES FROM 2..4
    random_horses = [2, 3]

    # 6) COLLECT ANY HORSE NUMBERS THAT PLAYERS SPECIFICALLY BET ON (excluding dealer=1)
    player_horses = list({bet.horse_number for bet in bets if bet.horse_number != dealer_horse})

    # 7) BUILD FULL LIST: [dealer=1] + two random + any extra player‐chosen horses
    all_horses = [dealer_horse] + random_horses
    for h in player_horses:
        if h not in all_horses:
            all_horses.append(h)

    distance  = race.race_distance  # e.g. 20
    positions = {h: distance for h in all_horses}

    # ─── LOAD OWNEDHORSE NAMES ──────────────────────────────────────────────────────
    owned_list = await sync_to_async(list)(
        OwnedHorse.objects.filter(horse_number__in=all_horses)
    )
    name_map = {h: f"Horse {h}" for h in all_horses}
    for oh in owned_list:
        if oh.name:
            name_map[oh.horse_number] = oh.name

    # 8) FETCH ALL APPLIED UPGRADES (“spells”) FOR THESE HORSES
    applied_list = await sync_to_async(
        lambda: list(
            HorseAppliedUpgrade.objects.filter(horse__horse_number__in=all_horses)
        )
    )()

    # Build a mapping: horse_number → list of upgrade names
    upgrades_map = {}
    for au in applied_list:
        horse_number = await sync_to_async(lambda: au.horse.horse_number)()
        upgrade_name = await sync_to_async(lambda: au.upgrade.name)()
        upgrades_map.setdefault(horse_number, []).append(upgrade_name)

    # 9) LOAD ANY CUSTOM EMOJI THAT OWNERS HAVE SET ON THEIR OwnedHorse
    owned_horses = await sync_to_async(list)(
        OwnedHorse.objects.filter(horse_number__in=all_horses)
    )
    horse_emojis = {oh.horse_number: oh.emoji for oh in owned_horses if oh.emoji}

    # 10) APPLY “🏁 Head Start” INITIAL POSITION BONUS
    for h in all_horses:
        if "🏁 Head Start" in upgrades_map.get(h, []):
            positions[h] = max(0, positions[h] - 4)

    # 11) INITIALIZE PER‐HORSE STATE FOR SPELLS THAT NEED IT
    tick_count       = 0
    last_movements   = {h: 1 for h in all_horses}
    freeze_used      = set()
    frozen_for_one   = set()
    bounce_used      = set()
    broken           = set()

    # 12) SEND INITIAL MESSAGE, THEN EDIT EACH TICK
    msg    = await update.message.reply_text("🏁 The race begins! 🐎")
    winner = None

    # ─── MAIN ANIMATION LOOP ────────────────────────────────────────────────────────
    while not winner:
        tick_count += 1
        frozen_for_one.clear()

        # 12a) “Freeze Ray”: each horse with that spell freezes one random rival (once per race)
        for h in all_horses:
            if "🧊 Freeze Ray" in upgrades_map.get(h, []):
                rivals = [r for r in all_horses if r != h and positions[r] > 0]
                if rivals:
                    victim = random.choice(rivals)
                    frozen_for_one.add(victim)

        # 12b) Compute each horse's movement this tick
        new_movements = {}
        for h in sorted(all_horses):
            # 1) If the horse has already finished, it doesn't move
            if positions[h] <= 0:
                new_movements[h] = 0
                continue

            # 2) If this horse is frozen this tick, it doesn't move
            if h in frozen_for_one:
                new_movements[h] = 0
                continue

            # 3) SPECIAL CASE: dealer’s horse (number 1) always moves 2–4 (no spells apply)
            if h == dealer_horse:
                # new_movements[h] = random.randint(2, 5)
                new_movements[h] = random.randint(
                    params.horse_move_min,
                    params.horse_move_max
                )
                continue

            # 4) Otherwise, check spells exactly as before
            spells = upgrades_map.get(h, [])

            # Mirror Trick
            if "🔮 Mirror Trick" in spells:
                others = [o for o in all_horses if o != h]
                if others:
                    chosen = random.choice(others)
                    new_movements[h] = last_movements.get(chosen, random.randint(1, 3))
                else:
                    new_movements[h] = random.randint(1, 3)
                continue

            # Steady Stride
            if "⚖️ Steady Stride" in spells:
                new_movements[h] = random.randint(1, 5)
                continue

            # Power Burst
            if "⚡ Power Burst" in spells:
                new_movements[h] = 4 if random.random() < 0.1 else 1
                continue

            # Triple Dash
            if "💨 Double Dash" in spells:
                new_movements[h] = 3
                continue

            # Cursed Sprint
            if "🛠 Cursed Sprint" in spells:
                if random.random() < 0.4:
                    broken.add(h)
                    new_movements[h] = 0
                else:
                    new_movements[h] = 5
                continue

            # Head Start
            if "🏁 Head Start" in spells:
                new_movements[h] = random.randint(1, 3)
                continue

            # Mutation
            if "🧬 Mutation" in spells:
                choice = random.choice([
                    "🔮 Mirror Trick",
                    "⚖️ Steady Stride",
                    "⚡ Power Burst",
                    "💨 Double Dash",
                    "🛠 Cursed Sprint",
                    "🏁 Head Start"
                ])
                if choice == "🔮 Mirror Trick":
                    others = [o for o in all_horses if o != h]
                    if others:
                        pick = random.choice(others)
                        new_movements[h] = last_movements.get(pick, random.randint(1, 3))
                    else:
                        new_movements[h] = random.randint(1, 3)
                elif choice == "⚖️ Steady Stride":
                    new_movements[h] = random.randint(1, 5)
                elif choice == "⚡ Power Burst":
                    new_movements[h] = 4 if random.random() < 0.1 else 1
                elif choice == "💨 Double Dash":
                    new_movements[h] = 3
                elif choice == "🛠 Cursed Sprint":
                    if random.random() < 0.4:
                        broken.add(h)
                        new_movements[h] = 0
                    else:
                        new_movements[h] = 5
                elif choice == "🏁 Head Start":
                    new_movements[h] = random.randint(1, 3)
                continue

            # 5) Default: random 1–3 for any non-dealer, non-spell horse
            new_movements[h] = random.randint(1, 4)

        # 12c) Apply all movements to positions
        prev_positions = positions.copy()
        for h, move in new_movements.items():
            positions[h] = max(0, positions[h] - move)

        # 12d) Magnet Pull: on every 3rd tick, horses with that spell slow all others by 1
        if tick_count % 3 == 0:
            for h in all_horses:
                if "🧲 Magnet Pull" in upgrades_map.get(h, []):
                    for other in all_horses:
                        if other != h and positions[other] > 0:
                            positions[other] = max(0, positions[other] + 1)

        # 12e) Bounce Back: if overtaken by ≥2, bounce 5 steps
        for h in all_horses:
            if "🦘 Bounce Back" in upgrades_map.get(h, []) and h not in bounce_used and positions[h] > 0:
                ahead_count = sum(
                    1
                    for o in all_horses
                    if o != h and positions[o] < positions[h] and positions[o] > 0
                )

                if ahead_count >= 2:
                    positions[h] = max(0, positions[h] - 5)
                    bounce_used.add(h)  # ✅ ensure it only happens once per horse


        # 12f) Build the “race_display” string (25‐dash track)
        race_display = ""
        for h in sorted(all_horses):
            emoji = horse_emojis.get(h, "🐎")
            label = name_map[h].replace(" ", "\u00A0")
            if len(label) > MAX_NAME_LEN:
                label = label[: MAX_NAME_LEN - 1] + "…"

            dash_count  = max(1, (positions[h] * 25) // distance)
            trail_count = max(1, 25 - dash_count)
            leading  = "-" * dash_count
            trailing = "-" * trail_count
            raw_track = f"{leading}\u200E{emoji}\u200E{trailing}"
            track = "\u202A" + raw_track + "\u202C"

            if is_rtl(label):
                rtl_label = "\u202B" + label + "\u202C"
            else:
                rtl_label = label

            combined = "\u202A" + track + "\u200E" + " " + rtl_label + "\u202C"

            if h in broken:
                race_display += f"🚫 | 💥 {combined} (broken!)\n"
            elif positions[h] == 0:
                race_display += f"🏆 | 🏁 {combined}\n"
                if winner is None:
                    winner = h
            else:
                race_display += f"🏆 | {combined}\n"

        # 12g) Truncate if too long
        if len(race_display) > MAX_MESSAGE_LEN:
            race_display = race_display[: MAX_MESSAGE_LEN - 1] + "\n…"

        # 12h) Attempt to edit the message; handle flood control
        try:
            await msg.edit_text(race_display)
        except RetryAfter as e:
            await asyncio.sleep(int(e.retry_after) + 1)
            continue

        # 12i) Pause before next tick
        await asyncio.sleep(0.8)
        last_movements = new_movements.copy()

    # ─── Once “winner” is set ───────────────────────────────────────────────────────
    if winner == dealer_horse:
        total_pot = sum(bet.bet_amount for bet in bets)
        dealer_obj, _ = await sync_to_async(Dealer.objects.get_or_create)(id=1)
        dealer_obj.chips += total_pot
        dealer_obj.wins  += 1
        dealer_obj.games += 1
        await sync_to_async(dealer_obj.save)()
        # Record dealer’s win
        await sync_to_async(HorseRaceWin.objects.create)(
            race=race,
            user=None,
            horse_number=dealer_horse,
            horse_name="Dealer",
            amount=total_pot
        )

        await update.message.reply_text(
            "🏆 Dealer's horse 1 wins! All players lose their bets."
        )
        au_qs = HorseAppliedUpgrade.objects.filter(
        horse__horse_number__in=all_horses
        )
        applied_upgrades = await sync_to_async(list)(au_qs.select_related("horse", "upgrade", "owner"))

        for applied in applied_upgrades:
            owner = applied.owner
            upgrade_name = applied.upgrade.name
            horse_number = applied.horse.horse_number

            # Subtract one use
            applied.uses_remaining -= 1

            if applied.uses_remaining > 0:
                # Still has uses left—save, and if now exactly 1, warn them:
                await sync_to_async(applied.save)()
                if applied.uses_remaining == 1:
                    await context.bot.send_message(
                        chat_id=owner.id,
                        text=(
                            f"⚠️ Your spell *{upgrade_name}* on "
                            f"Horse {horse_number} has only 1 use left!"
                        ),
                        parse_mode="Markdown"
                    )
            else:
                # No uses left—delete the applied upgrade and the purchase record
                await sync_to_async(applied.delete)()
                await sync_to_async(
                    PlayerUpgrade.objects.filter(
                        player=owner,
                        upgrade=applied.upgrade
                    ).delete
                )()

                # Notify them that the spell expired
                await context.bot.send_message(
                    chat_id=owner.id,
                    text=(
                        f"💥 Your spell *{upgrade_name}* on "
                        f"Horse {horse_number} has expired and been removed."
                    ),
                    parse_mode="Markdown"
                )


        return

    # ─── Players won ───────────────────────────────────────────────────────────────
    winning_bets      = [bet for bet in bets if bet.horse_number == winner]
    total_losing_bets = sum(bet.bet_amount for bet in bets if bet.horse_number != winner)

    if not winning_bets:
        total_pot = sum(bet.bet_amount for bet in bets)
        dealer_obj, _ = await sync_to_async(Dealer.objects.get_or_create)(id=1)
        dealer_obj.chips += total_pot
        dealer_obj.wins  += 1
        dealer_obj.games += 1
        await sync_to_async(dealer_obj.save)()

        # Record dealer’s win when no players bet
        horse_obj = await sync_to_async(lambda: OwnedHorse.objects.filter(horse_number=winner).first())()
        horse_name = horse_obj.name if (horse_obj and horse_obj.name) else ""
        await sync_to_async(HorseRaceWin.objects.create)(
            race=race,
            user=None,
            horse_number=winner,
            horse_name=horse_name,
            amount=total_pot
        )

        await safe_send_message(
            context.bot,
            chat_id,
            (
                f"🏆 Horse {winner} won, but no players bet on it!\n"
                f"🎰 Casino (Dealer) takes the pot: {total_pot:,} chips!"
            )
        )
    else:
        oh = await sync_to_async(lambda: OwnedHorse.objects.filter(horse_number=winner).first())()
        horse_label = oh.name if (oh and oh.name) else f"Horse {winner}"
        total_stakes = sum(bet.bet_amount for bet in bets)
        total_winning_stakes = sum(bet.bet_amount for bet in winning_bets)
        payout_pool = horse_race_payout_pool(total_stakes)

        # Record each player’s win
        for bet in winning_bets:
            payout = max(1, payout_pool * bet.bet_amount // total_winning_stakes)

            player_obj = await sync_to_async(Player.objects.get)(id=bet.user_id)
            payout_change = await adjust_balance_async(
                player_obj,
                payout,
                category=ChipTransaction.Category.RACE_PAYOUT,
                description=f"Horse race payout for horse {winner}",
                reference_type="horse_race",
                reference_id=race.id,
                idempotency_key=f"race:{race.id}:bet:{bet.id}:payout",
                metadata={
                    "horse_number": winner,
                    "bet_amount": bet.bet_amount,
                    "total_stakes": total_stakes,
                    "payout_pool": payout_pool,
                },
            )

            if payout_change.applied:
                await sync_to_async(HorseRaceWin.objects.create)(
                    race=race,
                    user=player_obj,
                    horse_number=winner,
                    horse_name=(oh.name if (oh and oh.name) else ""),
                    amount=payout,
                )

            await safe_send_message(
                context.bot,
                bet.user_id,
                f"🎉 You won {payout:,} chips on {horse_label}!"
            )
            if payout_change.applied:
                await apply_referral_bonus(player_obj, payout, context)
            await update_daily_quest_progress(player_obj, "race", "win", 1, context)

        first_share = max(
            1, payout_pool * winning_bets[0].bet_amount // total_winning_stakes
        )
        await safe_send_message(
            context.bot,
            chat_id,
            (
                f"🏆 Race finished! Winner: {horse_label} (#{winner}) 🏆\n"
                f"🎉 First winner’s payout: {first_share:,} chips!"
            )
        )

    race.completed = True
    race.completed_at = timezone.now()
    await sync_to_async(race.save)(update_fields=("completed", "completed_at"))

    # ─── Cleanup Used-Up Spells ────────────────────────────────────────────────────────
    # used_up_spells = await sync_to_async(list)(
    #     HorseAppliedUpgrade.objects.filter(uses_remaining__lte=0).select_related("upgrade", "horse")
    # )

    # for spell in used_up_spells:
    #     try:
    #         # Delete from PlayerUpgrade
    #         await sync_to_async(PlayerUpgrade.objects.filter(
    #             player=spell.owner,
    #             upgrade=spell.upgrade
    #         ).delete)()
    #     except Exception:
    #         pass  # failsafe — sometimes .owner isn't prefetched

    #     # Delete from applied upgrades
    #     await sync_to_async(spell.delete)()

    # ─── Do not delete the race; we keep it for history ─────────────────────────────
    au_qs = HorseAppliedUpgrade.objects.filter(
        horse__horse_number__in=all_horses
    )
    applied_upgrades = await sync_to_async(list)(au_qs.select_related("horse", "upgrade", "owner"))

    for applied in applied_upgrades:
        owner = applied.owner
        upgrade_name = applied.upgrade.name
        horse_number = applied.horse.horse_number

        # Subtract one use
        applied.uses_remaining -= 1

        if applied.uses_remaining > 0:
            # Still has uses left—save, and if now exactly 1, warn them:
            await sync_to_async(applied.save)()
            if applied.uses_remaining == 1:
                await context.bot.send_message(
                    chat_id=owner.id,
                    text=(
                        f"⚠️ Your spell *{upgrade_name}* on "
                        f"Horse {horse_number} has only 1 use left!"
                    ),
                    parse_mode="Markdown"
                )
        else:
            # No uses left—delete the applied upgrade and the purchase record
            await sync_to_async(applied.delete)()
            await sync_to_async(
                PlayerUpgrade.objects.filter(
                    player=owner,
                    upgrade=applied.upgrade
                ).delete
            )()

            # Notify them that the spell expired
            await context.bot.send_message(
                chat_id=owner.id,
                text=(
                    f"💥 Your spell *{upgrade_name}* on "
                    f"Horse {horse_number} has expired and been removed."
                ),
                parse_mode="Markdown"
            )












async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    await update.message.reply_text(
        "🏪 Shop Menu:\n"
        "/buyhorse <number> - Buy a horse number,(Costs 60000)\n"
        "/setemoji <horse_number> <emoji> - Set emoji for your horse(Costs 9000)\n"
        "/myhorses - View your owned horses"
    )




async def buyhorse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /buyhorse <horse_number>")
        return

    horse_number = int(args[0])
    if horse_number == 1:
        await update.message.reply_text("❌ Horse 1 is reserved for the dealer.")
        return

    cost = 60000
    try:
        await buy_horse_async(user_id, horse_number, cost)
    except HorseUnavailable:
        await update.message.reply_text("❌ This horse is already owned.")
        return
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered.")
        return
    except InsufficientChips:
        await update.message.reply_text("❌ Not enough chips! Horse costs 60,000.")
        return


    await update.message.reply_text(f"✅ You now own Horse {horse_number}!")



async def setemoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    user_id = update.effective_user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Usage: /setemoji <horse_number> <emoji>")
        return

    try:
        horse_number = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Horse number must be a valid number.")
        return

    emoji = args[1]
    emoji_cost = 9000

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        horse = await sync_to_async(OwnedHorse.objects.get)(horse_number=horse_number)

        horse_owner_id = await sync_to_async(lambda: horse.user.id)()

        if horse_owner_id != player.id:
            await update.message.reply_text("❌ You don’t own this horse.")
            return

        try:
            await customize_horse_async(
                player.id, horse_number, emoji_cost, emoji=emoji
            )
        except InsufficientChips:
            await update.message.reply_text("❌ Not enough chips to change the emoji.")
            return

        await update.message.reply_text(
            f"✅ Emoji updated to {emoji} for horse {horse_number}!\n💸 Cost: {emoji_cost} chips"
        )

    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You don’t own this horse.")


# ─── /myhorses: Show owned horses, their emojis, and owned/applied upgrades ───
async def myhorses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    user_id = update.effective_user.id
    player = await sync_to_async(Player.objects.get)(id=user_id)

    # Fetch all horses owned by this player
    horses = await sync_to_async(list)(
        OwnedHorse.objects.filter(user=player)
    )

    # Fetch all upgrades the player has purchased
    owned_upgrades = await sync_to_async(list)(
        PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
    )

    if not horses and not owned_upgrades:
        await update.message.reply_text("🐎 You don’t own any horses or spells yet.")
        return

    lines = []

    if horses:
        lines.append("🐴 *Your Horses:*")
        for h in horses:
            # For each horse, list applied upgrades
            applied = await sync_to_async(list)(
                HorseAppliedUpgrade.objects.filter(horse=h).select_related("upgrade")
            )
            applied_names = [ap.upgrade.name for ap in applied]
            emoji_text = f" {h.emoji}" if h.emoji else ""
            if applied_names:
                lines.append(f"• Horse {h.horse_number}{emoji_text}  _(Applied: {', '.join(applied_names)})_")
            else:
                lines.append(f"• Horse {h.horse_number}{emoji_text}")
    else:
        lines.append("🐴 You don’t own any horses.")

    if owned_upgrades:
        lines.append("\n🔧 *Your Purchased spells:*")
        for pu in owned_upgrades:
            lines.append(f"• {pu.upgrade.name}: {pu.upgrade.description} (Cost: {pu.upgrade.cost} chips)")
    else:
        lines.append("\n🔧 You haven’t purchased any spells.")

    message = "\n".join(lines)
    await update.message.reply_text(message, parse_mode="Markdown")


# ─── /shopupgrades: List available upgrades ───
async def shopupgrades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fetch all defined upgrades
    upgrades = await sync_to_async(list)(HorseUpgrade.objects.all())
    if not upgrades:
        await update.message.reply_text("No spells available right now.")
        return

    lines = ["🏬 *Available Spells:*",""]
    for up in upgrades:
        lines.append(
            f"{up.id}. *{up.name}* — {up.cost} chips\n"
            f"    _{up.description}_\n"
        )

    # Add instructions at the bottom
    lines.append("")  # blank line
    lines.append("ℹ️ To purchase a spell, type `/buyupgrade <spell_id>`.")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )

# ─── /buyupgrade <upgrade_id>: Purchase an upgrade ───
async def buyupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.effective_user.id
    args = context.args

    # Must pass exactly one integer (the upgrade’s ID)
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /buyspell <spell_id>")
        return
    upgrade_id = int(args[0])

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered.")
        return

    # Validate upgrade exists
    try:
        upgrade = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
    except HorseUpgrade.DoesNotExist:
        await update.message.reply_text("❌ Invalid spell ID.")
        return

    try:
        await buy_horse_upgrade_async(user_id, upgrade.id)
    except UpgradeAlreadyOwned:
        await update.message.reply_text("❌ You already own this spell.")
        return
    except InsufficientChips:
        await update.message.reply_text(f"❌ Not enough chips! This costs {upgrade.cost}.")
        return

    await update.message.reply_text(
        f"✅ You bought *{upgrade.name}*! You can now apply it to any of your horses.",
        parse_mode="Markdown"
    )

async def applyupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    user_id = update.effective_user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Usage: /applyspell <horse_number> <spell_id>")
        return

    # 1) Parse horse number and upgrade ID
    try:
        horse_number = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Horse number must be an integer.")
        return

    try:
        upgrade_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ spell ID must be an integer.")
        return

    # 2) Verify that this player actually owns that horse:
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id,
            horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text(f"❌ You do not own a horse numbered {horse_number}.")
        return

    # 3) Verify that the desired HorseUpgrade exists by ID:
    try:
        upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(pk=upgrade_id)
    except HorseUpgrade.DoesNotExist:
        await update.message.reply_text(f"❌ No upgrade found with ID {upgrade_id}.")
        return

    # 4) Check that the player has purchased this upgrade (PlayerUpgrade must exist)
    owns_upgrade_exists = await sync_to_async(
        lambda: PlayerUpgrade.objects.filter(player__id=user_id, upgrade=upgrade_obj).exists()
    )()
    if not owns_upgrade_exists:
        await update.message.reply_text(
            f"❌ You have not purchased the “{upgrade_obj.name}” spell (ID {upgrade_id})."
        )
        return

    # 5) Fetch all upgrade names already applied to this horse in one go (synchronously wrapped):
    existing_names = await sync_to_async(
        lambda: list(
            HorseAppliedUpgrade.objects.filter(horse=owned_horse)
                                     .values_list("upgrade__name", flat=True)
        )
    )()

    # 6) Prevent “Double Dash” and “Risky Rocket” from coexisting:
    blocking_pair = {"Double Dash", "Risky Rocket"}
    if upgrade_obj.name in blocking_pair:
        other_name = "Risky Rocket" if upgrade_obj.name == "Double Dash" else "Double Dash"
        if other_name in existing_names:
            await update.message.reply_text(
                f"❌ You cannot apply “{upgrade_obj.name}” (ID {upgrade_id}) to Horse {horse_number} "
                f"because it already has “{other_name}” applied."
            )
            return

    # 7) Check if this exact upgrade is already applied to that horse:
    already_applied = await sync_to_async(
        lambda: HorseAppliedUpgrade.objects.filter(
            owner__id=user_id,
            horse=owned_horse,
            upgrade=upgrade_obj
        ).exists()
    )()
    if already_applied:
        await update.message.reply_text(
            f"⚠️ Spell “{upgrade_obj.name}” (ID {upgrade_id}) is already applied to Horse {horse_number}."
        )
        return

    # 8) Finally, create the HorseAppliedUpgrade record:
    player_obj = await sync_to_async(Player.objects.get)(id=user_id)
    await sync_to_async(HorseAppliedUpgrade.objects.create)(
        owner=player_obj,
        horse=owned_horse,
        upgrade=upgrade_obj
    )

    await update.message.reply_text(
        f"✅ “{upgrade_obj.name}” (ID {upgrade_id}) has been applied to Horse {horse_number}!"
    )

# ─── /unapplyupgrade <horse_number> <upgrade_id> ───
async def unapplyupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.effective_user.id
    args = context.args

    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text("Usage: /unapplyspell <horse_number> <upgrade_id>")
        return
    horse_number = int(args[0])
    upgrade_id = int(args[1])

    # Fetch player
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered.")
        return

    # Check horse
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(horse_number=horse_number)
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You don’t own that horse.")
        return
    owner_id = await sync_to_async(lambda: owned_horse.user.id)()
    if owner_id != user_id:
        await update.message.reply_text("❌ You don’t own this horse.")
        return

    # Fetch upgrade
    try:
        upgrade = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
    except HorseUpgrade.DoesNotExist:
        await update.message.reply_text("❌ Invalid spell.")
        return

    # Check if applied
    applied_qs = await sync_to_async(HorseAppliedUpgrade.objects.filter)(
        owner=player, horse=owned_horse, upgrade=upgrade
    )
    if not await sync_to_async(applied_qs.exists)():
        await update.message.reply_text("❌ That spell isn’t applied to this horse.")
        return

    # Remove it
    await sync_to_async(applied_qs.delete)()
    await update.message.reply_text(
        f"✅ Unapplied *{upgrade.name}* from Horse {horse_number}.",
        parse_mode="Markdown"
    )

async def build_main_menu_keyboard():
    # Fetch game parameters
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

    # Dynamically change button labels
    buy_horse_label = "🐎 Buy Horse"
    if params.buyhorse_event:
        buy_horse_label += f" – Only Today {params.todays_horse_price:,}!"

    rename_horse_label = "✏️ Name Horse"
    if params.rename_horse_event:
        rename_horse_label += " Only (1 chip!)"

    # Build keyboard
    keyboard = [
        [
            InlineKeyboardButton(buy_horse_label, callback_data="menu:buy_horse"),
            InlineKeyboardButton("🎨 Set Emoji", callback_data="menu:set_emoji"),
        ],
        [
            InlineKeyboardButton("🐴 My Horses", callback_data="menu:my_horses"),
            InlineKeyboardButton("📜 My Spells", callback_data="menu:my_spells"),
        ],
        [
            InlineKeyboardButton("💰 Buy Spell", callback_data="menu:buy_spell"),
            InlineKeyboardButton("✨ Apply Spell", callback_data="menu:apply_spell"),
        ],
        [
            InlineKeyboardButton("❌ Unapply Spell", callback_data="menu:unapply_spell"),
        ],
        [
            InlineKeyboardButton(rename_horse_label, callback_data="menu:rename_horse"),
            InlineKeyboardButton("🎁 Gift Horse", callback_data="menu:gift_horse"),
        ],
        [
            InlineKeyboardButton("🐴 Leaderboard", callback_data="menu:global_horse_leaderboard"),
            InlineKeyboardButton("📈 Race Stats", callback_data="menu:my_horse_statsrace"),
        ],
        [
            InlineKeyboardButton("📈 List Horse For Sale", callback_data="menu:list_horse"),
        ],
        [
            InlineKeyboardButton("🛒 Horses on Sale", callback_data="menu:sale_horses"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)



# ─── /horse: send the top‐level shop menu ───
async def horse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏇 *Horse Racing Shop Menu* 🏇\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=await build_main_menu_keyboard()
    )































async def horse_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ─── Back to main menu ───
    if data == "menu:mainhorse":
        context.user_data.pop("awaiting_buy_horse", None)
        context.user_data.pop("awaiting_set_emoji", None)
        await query.edit_message_text(
            "🏇 *Horse Racing Shop Menu* 🏇\n\n"
            "Choose an option below:",
            parse_mode="Markdown",
            reply_markup=await build_main_menu_keyboard()
        )
        return

    # ─── Buy Horse submenu ───
    # ─── Buy Horse submenu (now shows sale listings, too) ───
    if data == "menu:buy_horse":
        # ─── 1) Static pricing rules text ───
        params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

            
        if params.buyhorse_event:
            event_price = params.todays_horse_price
            lines = [
                "🐎 *Buy Horse*\n",
                "• Reply with the exact horse number you want to buy \\(unowned\\)\\. Pricing rules:\n",
                "  – 1\\-digit \\(e\\.g\\. 7\\): ~100000~ {} chips\n".format(event_price),
                "  – 2\\-digit \\(e\\.g\\. 42\\): ~80000~ {} chips\n".format(event_price),
                "  – 3\\-digit \\(e\\.g\\. 123\\): ~60000~ {} chips\n".format(event_price),
                "  – “All\\-same” digits \\(e\\.g\\. 11, 777, 2222\\): ~120000~ {} chips\n".format(event_price)
            ]
        else:
            lines = [
                "🐎 *Buy Horse*\n",
                "• Reply with the exact horse number you want to buy \\(unowned\\)\\. Pricing rules:\n",
                "  – 1\\-digit \\(e\\.g\\. 7\\): 100000 chips\n",
                "  – 2\\-digit \\(e\\.g\\. 42\\): 80000 chips\n",
                "  – 3\\-digit \\(e\\.g\\. 123\\): 60000 chips\n",
                "  – “All\\-same” digits \\(e\\.g\\. 11, 777, 2222\\): 120000 chips\n"
            ]

        # ─── 2) Fetch all active sale listings ───
        sale_list = await sync_to_async(list)(
            HorseSale.objects
                .select_related("horse__user", "horse")
                .all()
        )

        if sale_list:
            lines.append("🛒 *Horses for Sale:*")
            # Collect OwnedHorse instances to query applied upgrades in bulk
            owned_horses = [listing.horse for listing in sale_list]

            # ─── 3) Bulk fetch all applied upgrades for these horses ───
            applied_list = await sync_to_async(list)(
                HorseAppliedUpgrade.objects
                    .filter(horse__in=owned_horses)
                    .select_related("upgrade", "horse")
            )

            # ─── 4) Build a mapping: horse_number → [list of spell names] ───
            spells_map = {oh.horse_number: [] for oh in owned_horses}
            for au in applied_list:
                num = au.horse.horse_number
                spells_map[num].append(au.upgrade.name)

            # ─── 5) Append each sale to the text block ───
            for listing in sale_list:
                oh = listing.horse
                price = listing.price
                number = oh.horse_number

                # (a) Base label: custom name or “Horse <number>”
                if oh.name:
                    display_label = f"{oh.name} \\({number}\\)"
                else:
                    display_label = f"Horse {number}"

                # (b) Emoji if set
                emoji_text = f"{oh.emoji} " if oh.emoji else ""

                # (c) Spells from spells_map
                spell_names = spells_map.get(number, [])
                if spell_names:
                    spells_text = " – Applied: " + ", ".join(spell_names)
                else:
                    spells_text = ""

                lines.append(f"  – {emoji_text}{display_label}{spells_text} — {price:,} chips")

            lines.append("")  # blank line before “↩️ Back”

        lines.append("↩️ Back")

        # ─── 6) Mark that a raw number should run the unowned‐purchase logic ───
        context.user_data["awaiting_buy_horse"] = True

        # ─── 7) Build the keyboard: one button per sale listing, plus Back ───
        keyboard = []
        if sale_list:
            for listing in sale_list:
                oh = listing.horse
                price = listing.price
                number = oh.horse_number

                if oh.name:
                    display_label = f"{oh.name} \\({number}\\)"
                else:
                    display_label = f"Horse {number}"

                emoji_text = f"{oh.emoji} " if oh.emoji else ""
                spell_names = spells_map.get(number, [])
                if spell_names:
                    spells_text = " – Applied: " + ", ".join(spell_names)
                else:
                    spells_text = ""

                btn_text = f"{emoji_text}{display_label}{spells_text} — {price:,} chips"
                keyboard.append([
                    InlineKeyboardButton(
                        btn_text,
                        callback_data=f"menu:buy_sale:{number}"
                    )
                ])

        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Global Horse‐Racing Leaderboard (no backticks) ─────────────────────────
    if data == "menu:global_horse_leaderboard":
        # 1) Annotate wins & chips per player
        leaderboard_qs = await sync_to_async(
            lambda: list(
                HorseRaceWin.objects
                    .filter(user__isnull=False)
                    .values("user__id", "user__name")
                    .annotate(
                        wins=Count("id"),
                        chips=Sum("amount")
                    )
                    .order_by("-wins", "-chips")
            )
        )()

        top5 = leaderboard_qs[:5]
        user_id = query.from_user.id

        # Find calling user’s index
        user_index = next(
            (idx for idx, e in enumerate(leaderboard_qs) if e["user__id"] == user_id),
            None
        )

        # Build lines without backticks:
        lines = ["🌍 *Global Leaderboard* 🌍", ""]

        # Top 5 entries
        for idx, entry in enumerate(top5, start=1):
            name = entry["user__name"] or f"User {entry['user__id']}"
            wins = entry["wins"]
            chips_amt = entry["chips"] or 0
            # Format: "1 . Alice      🏆 Wins: 12   💰 Chips: 4800"
            # Use fixed‐width fields by padding/truncating name to ~10 chars
            lines.append(
                f"{idx:>2} . {name:<12}   🏆 Wins: {wins:<3}   💰 Chips: {chips_amt}"
            )

        lines.append("")  # blank separator

        # “Your Position” section
        if user_index is None:
            lines.append("🏅 *Your Position* (Not Ranked Yet):")
            lines.append("   • No wins recorded.")
        else:
            user_rank = user_index + 1
            lines.append(f"🏅 *Your Position* (Rank {user_rank}):")

            # Show up to two above and two below
            start = max(0, user_index - 2)
            end = min(len(leaderboard_qs), user_index + 3)
            for idx in range(start, end):
                e = leaderboard_qs[idx]
                name = e["user__name"] or f"User {e['user__id']}"
                wins = e["wins"]
                chips_amt = e["chips"] or 0
                display_rank = idx + 1
                prefix = "👉" if e["user__id"] == user_id else "  "
                lines.append(
                    f"{prefix}{display_rank:>2} . {name:<12}   🏆 Wins: {wins:<3}   💰 Chips: {chips_amt}"
                )

        text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    # ─── Race Stats ───────────────────────────────────────────────────────────────
    # ─── My Horse‐Racing Stats ─────────────────────────────────────────────────
    if data == "menu:my_horse_statsrace":
        user_id = query.from_user.id

        # 1) Total races this user has participated in (i.e. placed ≥1 bet)
        races_participated = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .values_list("race", flat=True)
                                     .distinct()
                                     .count()
        )()

        # 2) Total chips wagered by this user (sum of all their HorseBet.bet_amount)
        total_wagered_q = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .aggregate(total=Sum("bet_amount"))
        )()
        total_wagered = total_wagered_q["total"] or 0

        # 3) Average bet size for this user
        avg_bet_q = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .aggregate(avg=Avg("bet_amount"))
        )()
        avg_bet = avg_bet_q["avg"] or 0

        # 4) Total horses owned by this user
        horses_owned = await sync_to_async(
            lambda: OwnedHorse.objects.filter(user__id=user_id).count()
        )()

        # 5) Total wins (number of times this user appears in HorseRaceWin)
        total_wins = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id).count()
        )()

        # 6) Total chips earned (sum of HorseRaceWin.amount where user=this user)
        total_earned_q = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id)
                                         .aggregate(total=Sum("amount"))
        )()
        total_earned = total_earned_q["total"] or 0

        # 7) Horse‐Level Win Rate: For each horse this user owns,
        #    compute (wins_of_that_horse) / (bets_on_that_horse by this user).
        #    Then average across all their horses. If user has no horses, skip.
        horse_ids = await sync_to_async(
            lambda: list(
                OwnedHorse.objects.filter(user__id=user_id)
                                  .values_list("horse_number", flat=True)
            )
        )()

        if horse_ids:
            win_rate_list = []
            for hnum in horse_ids:
                wins_for_horse = await sync_to_async(
                    lambda: HorseRaceWin.objects.filter(
                        user__id=user_id, horse_number=hnum
                    ).count()
                )()
                bets_on_horse = await sync_to_async(
                    lambda: HorseBet.objects.filter(
                        user_id=user_id, horse_number=hnum
                    ).count()
                )()
                if bets_on_horse > 0:
                    win_rate_list.append(wins_for_horse / bets_on_horse)
                else:
                    win_rate_list.append(0.0)

            # Average across all horses
            horse_win_rate = (sum(win_rate_list) / len(win_rate_list)) * 100  # as percentage
        else:
            horse_win_rate = 0.0

        # 8) Player Win Rate: (# races in which they bet AND won) / (# races participated)
        #    “Races in which they won” = distinct race IDs from HorseRaceWin for this user
        races_won = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id)
                                        .values_list("race", flat=True)
                                        .distinct()
                                        .count()
        )()

        if races_participated > 0:
            player_win_rate = (races_won / races_participated) * 100
        else:
            player_win_rate = 0.0

        # ─── Build a Markdown block using the same “🎮 Your Stats 🎮” style ────────
        lines = [
            "🎮 *Your Horse‐Racing Stats* 🎮",
            "",
            f"🐎 Races participated: *{races_participated}*",
            f"💰 Total chips wagered: *{total_wagered:,}* chips",
            f"📊 Avg. bet size: *{avg_bet:.2f}* chips",
            f"🏠 Horses owned: *{horses_owned}*",
            f"🏆 Total wins: *{total_wins}*",
            f"🎉 Total chips earned: *{total_earned:,}* chips",
            f"🐴 Horse‐level win rate: *{horse_win_rate:.1f}%*",
            f"🎲 Player win rate: *{player_win_rate:.1f}%*",
        ]
        text = "\n".join(lines)

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return








    if data == "menu:set_emoji":
        user_id = query.from_user.id
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )

        if not owned_horses:
            text = "🎨 You don’t own any horses to set an emoji on.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for h in owned_horses:
            # Determine display label: “Name (number)” if name exists, else “Horse <number>”
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"

            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:setemoji_choose:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "🎨 *Set Emoji* – Choose which horse to change:\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        #
    # ─── “Sale Horses” submenu ───
    #
    #
    # ─── “Sale Horses” submenu — show spells + name/emoji + price ───
    #
    if data == "menu:sale_horses":
        # 1) Fetch all active listings (with select_related to grab the OwnedHorse itself)
        sale_list = await sync_to_async(list)(
            HorseSale.objects
                .select_related("horse__user", "horse")
                .all()
        )

        if not sale_list:
            text = "🛒 There are currently no horses listed for sale.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # 2) Build a list of just the OwnedHorse objects for these listings
        owned_horses = [listing.horse for listing in sale_list]

        # 3) In one bulk call, fetch all HorseAppliedUpgrade records for those OwnedHorse IDs
        #    We use `horse__in=owned_horses` and select_related("upgrade") so we get each upgrade name.
        applied_list = await sync_to_async(list)(
            HorseAppliedUpgrade.objects
                .filter(horse__in=owned_horses)
                .select_related("upgrade", "horse")
        )

        # 4) Build a mapping: horse_number → [list of spell names]
        spells_map = {}
        for h in owned_horses:
            spells_map[h.horse_number] = []
        for au in applied_list:
            num = au.horse.horse_number
            spells_map[num].append(au.upgrade.name)

        # 5) Now build the keyboard—pure Python from here on (no more ORM calls)
        keyboard = []
        for listing in sale_list:
            oh = listing.horse
            price = listing.price
            number = oh.horse_number

            # (a) Display label: custom name or “Horse <number>”
            if oh.name:
                display_label = f"{oh.name} ({number})"
            else:
                display_label = f"Horse {number}"

            # (b) Emoji (if any)
            emoji_text = f"{oh.emoji} " if oh.emoji else ""

            # (c) Spells (look up in spells_map)
            spell_names = spells_map.get(number, [])
            if spell_names:
                spells_text = " – Applied: " + ", ".join(spell_names)
            else:
                spells_text = ""

            # (d) Construct button text
            btn_text = f"{emoji_text}{display_label}{spells_text} — {price:,} chips"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:buy_sale:{number}"
                )
            ])

        # 6) Add the Back button at the bottom
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        # 7) Finally, edit the message
        await query.edit_message_text(
            "🛒 *Horses for Sale:*  (Tap to buy)\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

#
# ─── “Buy Sale Listing” handler ────────────────────────────────────────────────
#
    if data.startswith("menu:buy_sale:"):
        horse_number = int(data.split(":")[2])
        buyer_id = query.from_user.id
        print(f"[BUY_SALE] Buyer {buyer_id} clicked horse #{horse_number}")

        # 1) Fetch the listing & related OwnedHorse
        try:
            sale = await sync_to_async(
                HorseSale.objects.select_related("horse__user").get
            )(horse__horse_number=horse_number)
            print(f"[BUY_SALE] Found sale listing id={sale.id}")
        except HorseSale.DoesNotExist:
            print("[BUY_SALE] Listing no longer exists")
            await query.edit_message_text("❌ That listing no longer exists.\n\n↩️ Back")
            return

        owned_horse = sale.horse
        seller      = owned_horse.user
        price       = sale.price
        print(
            f"[BUY_SALE] Horse owner={seller.id} price={price:,} "
            f"emoji='{owned_horse.emoji}' name='{owned_horse.name}'"
        )

        # 2) Prevent self-purchase
        if seller.id == buyer_id:
            print("[BUY_SALE] Buyer tried to buy own horse – blocked")
            await query.edit_message_text("❌ You cannot buy your own listing.\n\n↩️ Back")
            return

        # 3) Atomically transfer payment, ownership, and remove the listing
        try:
            sale_result = await purchase_horse_sale_async(buyer_id, horse_number)
        except InsufficientChips:
            buyer = await sync_to_async(Player.objects.get)(id=buyer_id)
            await query.edit_message_text(
                f"❌ Not enough chips! You need {price:,} but you have {buyer.chips:,}.\n\n↩️ Back"
            )
            return
        except InvalidHorseSale:
            await query.edit_message_text("❌ That listing is no longer available.\n\n↩️ Back")
            return

        buyer = sale_result.buyer
        seller_player = sale_result.seller
        owned_horse = sale_result.horse
        price = sale_result.price

        # 7) Notify both parties
        display_label = (
            f"{owned_horse.name} ({horse_number})" if owned_horse.name
            else f"Horse {horse_number}"
        )

        await query.edit_message_text(
            f"✅ You bought {display_label} from {seller_player.name or seller_player.id} "
            f"for {price:,} chips!"
        )
        print(f"[BUY_SALE] Buyer message sent")

        # Try DM’ing the seller
        try:
            await context.bot.send_message(
                chat_id=seller_player.id,
                text=(
                    f"🎉 Your horse {display_label} was purchased by "
                    f"{buyer.name or buyer.id} for {price:,} chips!"
                )
            )
            print(f"[BUY_SALE] Seller DM sent")
        except Exception as e:
            print(f"[BUY_SALE] Could not DM seller: {e}")

        return

    # ─── My Horses submenu (show horses + owned spells) ───
        # ─── “List Horse” submenu ───
    #
    if data == "menu:list_horse":
        user_id = query.from_user.id
        # Fetch all horses this user owns that are NOT already listed
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects
                      .filter(user__id=user_id)
                      .exclude(sale_listing__isnull=False)
        )
        if not owned_horses:
            text = "📈 You don’t have any horses available to list for sale.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a keyboard listing each owned horse (showing name(number) or “Horse <number>”)
        keyboard = []
        for h in owned_horses:
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"
            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:list_choose:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "📈 *List Horse for Sale* – Choose which of your horses to list:\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── “List Horse → Pick Horse” ───
    #
    if data.startswith("menu:list_choose:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # Verify user still owns that horse and it’s not already listed
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Make sure it isn't already listed
        if await sync_to_async(
            HorseSale.objects.filter(horse=owned_horse).exists
        )():
            await query.edit_message_text(
                f"⚠️ That horse is already listed for sale.\n\n↩️ Back",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]])
            )
            return

        # Save in user_data so text‐handler knows we’re in “awaiting_list_price” mode
        context.user_data["awaiting_list_horse"] = horse_number

        # Ask the user for the price
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            f"📈 *List → {display_label}*\n\n"
            "Please reply with the price (in chips) at which you want to list this horse for sale.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    if data == "menu:my_horses":
        user_id = query.from_user.id
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text("❌ You’re not registered yet.")
            return

        horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user=player)
        )
        owned_upgrades = await sync_to_async(list)(
            PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
        )

        if not horses and not owned_upgrades:
            text = "🐎 You don’t own any horses yet.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        lines = []
        if horses:
            lines.append("🐴 *Your Horses:*")
            for h in horses:
                # Fetch any applied upgrades
                applied = await sync_to_async(list)(
                    HorseAppliedUpgrade.objects.filter(horse=h).select_related("upgrade")
                )
                applied_names = [ap.upgrade.name for ap in applied]

                # Determine display label: if custom name exists, show "Name(number)"
                if h.name:
                    display_label = f"{h.name} ({h.horse_number})"
                else:
                    display_label = f"Horse {h.horse_number}"

                emoji_text = f" {h.emoji}" if h.emoji else ""

                if applied_names:
                    lines.append(
                        f"• {display_label}{emoji_text}  _(Applied: {', '.join(applied_names)})_"
                    )
                else:
                    lines.append(f"• {display_label}{emoji_text}")
        else:
            lines.append("🐴 You don’t own any horses.")

        lines.append("\n↩️ Back")
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return


        # if owned_upgrades:
        #     lines.append("\n🔧 *Your Purchased Spells:*")
        #     for pu in owned_upgrades:
        #         lines.append(
        #             f"• {pu.upgrade.name} – {pu.upgrade.description} _(Cost: {pu.upgrade.cost})_"
        #         )
        # else:
        #     lines.append("\n🔧 You haven’t purchased any spells.")

        # lines.append("\n↩️ Back")
        # keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:main")]]
        # await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
        #                               reply_markup=InlineKeyboardMarkup(keyboard))
        # return
    if data == "menu:rename_horse":
        user_id = query.from_user.id
        # Fetch all horses owned by this user
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )

        if not owned_horses:
            text = "✏️ You don’t own any horses to rename.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a keyboard listing each horse (show name if set, else “Horse <number>”)
        params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)
        if params.rename_horse_event:

            lines = ["✏️ *Rename Horse* ~60 000 chips~ 1 chip – Choose which horse to rename:",""]
        else:
            lines = ["✏️ *Rename Horse* (60 000 chips) – Choose which horse to rename:",""]
        keyboard = []
        for h in owned_horses:
            display = h.name if h.name else f"Horse {h.horse_number}"
            keyboard.append([
                InlineKeyboardButton(
                    display,
                    callback_data=f"menu:rename_choose:{h.horse_number}"
                )
            ])

        # Back button
        keyboard.append([ InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse") ])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    if data == "menu:gift_horse":
        user_id = query.from_user.id

        # Offer two choices: gift an owned horse, or buy+gift a new one
        keyboard = [
            [InlineKeyboardButton("🎁 Gift Owned Horse",    callback_data="menu:gift_owned")],
            [InlineKeyboardButton("🎁 Buy & Gift Horse",    callback_data="menu:buy_and_gift")],
            [InlineKeyboardButton("↩️ Back",                 callback_data="menu:mainhorse")],
        ]
        await query.edit_message_text(
            "🎁 *Gift Horse* – Choose an option:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── Gift Owned Horse → Show List of Owned Horses ───
    #
    if data == "menu:gift_owned":
        user_id = query.from_user.id
        # Fetch all horses the user owns:
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )
        if not owned_horses:
            text = "❌ You don’t own any horses to gift.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a keyboard listing each owned horse (show name(number) or Horse <number>)
        keyboard = []
        for h in owned_horses:
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"
            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(btn_text, callback_data=f"menu:gift_owned_choose:{h.horse_number}")
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")])

        await query.edit_message_text(
            "🎁 *Gift Owned Horse* – Choose which horse to gift:\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── Gift Owned → Picked a Horse to Gift ───
    #
    if data.startswith("menu:gift_owned_choose:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # Verify the user still owns that horse
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Save flag + which horse they intend to gift
        context.user_data["awaiting_gift_owned"] = horse_number

        # Ask them for the recipient’s Telegram @username or ID
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
        await query.edit_message_text(
            f"🎁 *Gift → {display_label}*\n\n"
            "Please reply with the recipient’s numeric user ID (they can run /myid to see it).\n"
            "Fee: 10 000 chips.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── Buy & Gift Horse → Ask for the horse number to buy & gift ───
    #
    if data == "menu:buy_and_gift":
        # Mark that we’re in “buy and gift” mode
        context.user_data["awaiting_buy_and_gift"] = True

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
        await query.edit_message_text(
            "🎁 *Buy & Gift Horse* – Please reply with the horse number you want to purchase and gift.\n\n"
            "Cost = normal purchase cost for that number. ↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── “My Spells” submenu (new) ───
    if data == "menu:my_spells":
        user_id = query.from_user.id

        # Fetch the Player (if they exist)
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text("❌ You’re not registered yet.")
            return

        # Get all spells this player has purchased
        owned_upgrades = await sync_to_async(list)(
            PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
        )

        if not owned_upgrades:
            text = "🔧 You haven’t purchased any spells yet.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a simple list of “name – description (cost)”
        lines = ["🔧 *Your Purchased Spells:*",""]
        for pu in owned_upgrades:
            lines.append(f"• *{pu.upgrade.name}* — {pu.upgrade.description} _(Cost: {pu.upgrade.cost})_")
        # lines.append("\n↩️ Back")

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Buy Spell submenu ───
    if data == "menu:buy_spell":
        upgrades = await sync_to_async(list)(HorseUpgrade.objects.all())
        if not upgrades:
            text = "📜 No spells available right now.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        lines = ["📜 *Available Spells:*",""]
        keyboard = []
        for up in upgrades:
            lines.append(f"{up.id}. *{up.name}* – {up.description} _(Cost: {up.cost})_\n")
            keyboard.append([
                InlineKeyboardButton(
                    f"{up.name} (Cost: {up.cost})",
                    callback_data=f"menu:buy_spell_choose:{up.id}"
                )
            ])
        lines.append("\n↩️ Back")
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Apply Spell submenu ───
    if data == "menu:apply_spell":
        user_id = query.from_user.id
        horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )
        if not horses:
            text = "❌ You don’t own any horses to apply a spell to.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for h in horses:
            # Build display label: “Name (number)” if name exists, else “Horse <number>”
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"

            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:apply_choose_horse:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])
        await query.edit_message_text(
            "✨ *Apply Spell* – Choose which horse to enhance:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return










    if data == "menu:unapply_spell":
        user_id = query.from_user.id
        horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )
        if not horses:
            text = "❌ You don’t own any horses to remove a spell from.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for h in horses:
            # Build display label: “Name (number)” if name exists, else “Horse <number>”
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"

            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:unapply_choose_horse:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])
        await query.edit_message_text(
            "❌ *Unapply Spell* – Pick a horse:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("menu:rename_choose:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # Verify they own that horse
        try:
            await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Set the flag so catch_all_text knows we’re in “rename” mode
        context.user_data["awaiting_rename_horse"] = horse_number

        keyboard = [[ InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse") ]]
        params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)
        if params.rename_horse_event:
            await query.edit_message_text(
                f"✏️ *Rename → Horse {horse_number}*\n\n"
                "Please send the new name for your horse.\n"
                "Cost: 1 chip.\n\n↩️ Back",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        else:
            await query.edit_message_text(
                f"✏️ *Rename → Horse {horse_number}*\n\n"
                "Please send the new name for your horse.\n"
                "Cost: 60 000 chips.\n\n↩️ Back",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    if data.startswith("menu:setemoji_choose:"):
        horse_number = int(data.split(":")[2])

        # Fetch the OwnedHorse so we can show its label in the prompt
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=query.from_user.id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        # ── INSERT PRINT HERE ──
        print("DEBUG: awaiting_set_emoji set to", horse_number)
        context.user_data["awaiting_set_emoji"] = horse_number

        # Now ask the user to send their new emoji:
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            f"🎨 *Set Emoji → {display_label}*\n\n"
            "Please send the emoji you want to assign to this horse.\n"
            "Cost: 9 000 chips.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return











    #
    # ─── SUBMENU: “Buy Spell → Choose Spell” ───
    #
    if data.startswith("menu:buy_spell_choose:"):
        upgrade_id = int(data.split(":")[2])
        user_id = query.from_user.id

        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text("❌ You’re not registered.")
            return

        try:
            upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
        except HorseUpgrade.DoesNotExist:
            await query.edit_message_text("❌ That spell no longer exists.")
            return

        try:
            await buy_horse_upgrade_async(user_id, upgrade_obj.id)
        except UpgradeAlreadyOwned:
            await query.edit_message_text(
                f"⚠️ You already own *{upgrade_obj.name}*.",
                parse_mode="Markdown"
            )
            return
        except InsufficientChips:
            await query.edit_message_text(
                f"❌ Not enough chips! *{upgrade_obj.name}* costs {upgrade_obj.cost}.",
                parse_mode="Markdown"
            )
            return

        await query.edit_message_text(
            f"✅ You bought *{upgrade_obj.name}*!",
            parse_mode="Markdown"
        )
        return

        #
    # ─── SUBMENU: “Apply Spell → Choose Horse” ───
    #
    if data.startswith("menu:apply_choose_horse:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # 1) Verify horse ownership
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Build display_label = "Name (66)" if name exists, else "Horse 66"
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        # 2) Check if any upgrade is already applied to this horse
        existing_count = await sync_to_async(
            lambda: HorseAppliedUpgrade.objects.filter(horse=owned_horse).count()
        )()
        if existing_count > 0:
            # Only one upgrade allowed per horse
            text = (
                f"⚠️ {display_label} already has an upgrade applied.\n"
                "You can only apply one upgrade per horse.\n\n↩️ Back"
            )
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:apply_spell")]]
            await query.edit_message_text(text, parse_mode="Markdown",
                                          reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # 3) Fetch all spells the user has purchased
        player = await sync_to_async(Player.objects.get)(id=user_id)
        owned_spells = await sync_to_async(list)(
            PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
        )
        if not owned_spells:
            text = f"🔧 You haven’t purchased any spells to apply to {display_label}.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:apply_spell")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # 4) Build a keyboard listing each owned spell
        keyboard = []
        for pu in owned_spells:
            up = pu.upgrade
            keyboard.append([InlineKeyboardButton(
                up.name,
                callback_data=f"menu:apply_choose_spell:{horse_number}:{up.id}"
            )])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:apply_spell")])

        # Use display_label in the header
        await query.edit_message_text(
            f"✨ *Apply Spell → {display_label}*\n\n"
            "Choose which spell to apply (only one per horse):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return










    #
    # ─── SUBMENU: “Apply Spell → Confirm” ───
    #
    if data.startswith("menu:apply_choose_spell:"):
        parts = data.split(":")
        horse_number = int(parts[2])
        upgrade_id = int(parts[3])
        user_id = query.from_user.id

        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.")
            return

        try:
            upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
        except HorseUpgrade.DoesNotExist:
            await query.edit_message_text("❌ That spell no longer exists.")
            return

        has_it = await sync_to_async(
            PlayerUpgrade.objects.filter(player__id=user_id, upgrade=upgrade_obj).exists
        )()
        if not has_it:
            await query.edit_message_text("❌ You haven’t purchased that spell.")
            return

        blocking_pair = {"Double Dash", "Risky Rocket"}
        if upgrade_obj.name in blocking_pair:
            other_name = "Risky Rocket" if upgrade_obj.name == "Double Dash" else "Double Dash"
            existing_names = await sync_to_async(
                lambda: list(
                    HorseAppliedUpgrade.objects.filter(horse=owned_horse)
                                               .values_list("upgrade__name", flat=True)
                )
            )()
            if other_name in existing_names:
                await query.edit_message_text(
                    f"❌ You cannot apply *{upgrade_obj.name}* because *{other_name}* is already on Horse {horse_number}.",
                    parse_mode="Markdown"
                )
                return

        other_horse_number = await sync_to_async(
            lambda: HorseAppliedUpgrade.objects
                .filter(owner__id=user_id, upgrade=upgrade_obj)
                .exclude(horse=owned_horse)
                .values_list('horse__horse_number', flat=True)
                .first()
        )()
        
        if other_horse_number:
            await query.edit_message_text(
                f"❌ You’ve already applied *{upgrade_obj.name}* to "
                f"Horse {other_horse_number}, so you can’t apply it here too.",
                parse_mode="Markdown"
            )
            return

        # 2) Then check “already on this same horse?”
        already_on_this = await sync_to_async(
            HorseAppliedUpgrade.objects
                .filter(owner__id=user_id, horse=owned_horse, upgrade=upgrade_obj)
                .exists
        )()
        if already_on_this:
            await query.edit_message_text(
                f"⚠️ You already applied *{upgrade_obj.name}* to Horse {horse_number}.",
                parse_mode="Markdown"
            )
            return

        # 3) If neither check blocked you, it’s safe to apply:
        player_obj = await sync_to_async(Player.objects.get)(id=user_id)

        await sync_to_async(HorseAppliedUpgrade.objects.create)(
            owner=player_obj,
            horse=owned_horse,
            upgrade=upgrade_obj
        )
        
        await query.edit_message_text(
            f"✅ *{upgrade_obj.name}* has been applied to Horse {horse_number}!",
            parse_mode="Markdown"
        )
        return
       #
    # ─── SUBMENU: “Unapply Spell → Choose Horse” ───


    if data.startswith("menu:unapply_choose_horse:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.")
            return

        # Build display_label = "Name (66)" if name exists, else "Horse 66"
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        # Fetch all applied upgrades on this horse
        applied_list = await sync_to_async(
            lambda: list(
                HorseAppliedUpgrade.objects
                    .filter(horse=owned_horse)
                    .select_related("upgrade")
            )
        )()

        if not applied_list:
            text = f"⚠️ {display_label} has no spells to remove.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:unapply_spell")]]
            try:
                await query.edit_message_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # Build a list of “Spell Name” buttons for each applied upgrade
        lines = [f"❌ *Unapply Spell → {display_label}*",""]
        keyboard = []
        for ap in applied_list:
            up = ap.upgrade
            callback_str = f"menu:unapply_choose_spell:{horse_number}:{up.id}"
            lines.append(f"• *{up.name}* — {up.description}")
            keyboard.append([InlineKeyboardButton(up.name, callback_data=callback_str)])

        # Add a Back button at the bottom
        lines.append("\n↩️ Back")
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:unapply_spell")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return










    #
    # ─── SUBMENU: “Unapply Spell → Confirm” ───
    #
    if data.startswith("menu:unapply_choose_spell:"):
        parts = data.split(":")
        horse_number = int(parts[2])
        upgrade_id = int(parts[3])
        user_id = query.from_user.id

        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.")
            return

        try:
            upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
        except HorseUpgrade.DoesNotExist:
            await query.edit_message_text("❌ That spell no longer exists.")
            return

        applied_qs = await sync_to_async(HorseAppliedUpgrade.objects.filter)(
            owner__id=user_id, horse=owned_horse, upgrade=upgrade_obj
        )
        if not await sync_to_async(applied_qs.exists)():
            await query.edit_message_text(
                f"❌ *{upgrade_obj.name}* is not applied to Horse {horse_number}.",
                parse_mode="Markdown"
            )
            return

        # 5) Delete the applied upgrade
        await sync_to_async(applied_qs.delete)()
        await query.edit_message_text(
            f"✅ Unapplied *{upgrade_obj.name}* from Horse {horse_number}.",
            parse_mode="Markdown"
        )
        return


    # ─── Fallback → show main menu ───
    context.user_data.pop("awaiting_buy_horse", None)
    context.user_data.pop("awaiting_set_emoji", None)
    await query.edit_message_text(
        "🏇 *Horse Racing Shop Menu* 🏇\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=await build_main_menu_keyboard()
    )









































async def catch_gift_owned_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    horse_number = context.user_data.pop("awaiting_gift_owned", None)
    if horse_number is None:
        await update.message.reply_text("❌ No horse selected to gift. Aborting.")
        return

    # Re‐verify ownership (same as before) …
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id, horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You no longer own that horse. Aborting.")
        return

    fee = 10_000

    # ─── NEW: Only accept numeric user ID ───
    try:
        recipient_id = int(text)
    except ValueError:
        # Not a valid integer
        await update.message.reply_text(
            "❌ That is not a valid numeric user ID. "
            "Please have the recipient send /myid to the bot and paste that number here."
        )
        return

    # Look up the Player by ID
    try:
        recipient_player = await sync_to_async(Player.objects.get)(id=recipient_id)
    except Player.DoesNotExist:
        await update.message.reply_text(
            f"❌ No player in our database has ID {recipient_id}. "
            "Make sure they ran /myid and gave you their correct number."
        )
        return

    try:
        owned_horse = await gift_owned_horse_async(
            user_id, recipient_id, horse_number, fee
        )
    except InsufficientChips:
        await update.message.reply_text(
            f"❌ Not enough chips! You need {fee:,} to gift this horse."
        )
        return
    except HorseNotOwned:
        await update.message.reply_text("❌ You no longer own that horse. Aborting.")
        return

    # Notify both parties
    if owned_horse.name:
        display_label = f"{owned_horse.name} ({horse_number})"
    else:
        display_label = f"Horse {horse_number}"

    await update.message.reply_text(
        f"🎁 You gifted {display_label} to player‐ID {recipient_player.id}! (−{fee:,} chips)"
    )
    try:
        await context.bot.send_message(
            chat_id=recipient_player.id,
            text=f"🎁 You have received {display_label}! Enjoy your new horse."
        )
    except Exception:
        # Bot might not be able to DM if user hasn’t started it
        pass

    return



async def catch_buy_and_gift_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called when the user chose “Buy & Gift Horse” and now replies with a <horse_number>.
    Deduct normal purchase cost, then prompt for the recipient.
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Clear the “awaiting_buy_and_gift” flag
    if not context.user_data.get("awaiting_buy_and_gift"):
        return
    context.user_data.pop("awaiting_buy_and_gift", None)

    # 1) Validate numeric
    if not text.isdigit():
        await update.message.reply_text("❌ That’s not a valid horse number. Aborting.")
        return

    horse_number = int(text)
    # 2) Cannot buy reserved (1,2,3)
    if horse_number in (1, 2, 3):
        await update.message.reply_text(
            "❌ Horse 1, 2, and 3 are reserved. ↩️ Try again."
        )
        return

    # 3) Check if already owned
    exists_qs = await sync_to_async(OwnedHorse.objects.filter)(horse_number=horse_number)
    if await sync_to_async(exists_qs.exists)():
        await update.message.reply_text(
            f"❌ Horse {horse_number} is already owned. Use Gift Owned Horse instead."
        )
        return

    # 4) Compute purchase cost
    s = str(horse_number)
    if len(s) == 1:
        cost = 100_000
    elif len(s) == 2:
        cost = 120_000 if s[0] == s[1] else 80_000
    elif len(s) == 3:
        cost = 120_000 if (s[0] == s[1] == s[2]) else 60_000
    else:
        cost = 120_000 if all(ch == s[0] for ch in s) else 60_000

    # 5) Fetch player & check chips
    player = await sync_to_async(Player.objects.get)(id=user_id)
    if player.chips < cost:
        await update.message.reply_text(
            f"❌ Not enough chips! You need {cost:,} to buy Horse {horse_number}."
        )
        return

    # Record the quoted cost; payment and ownership commit after recipient validation.
    context.user_data["purchased_gift_horse"] = horse_number
    context.user_data["purchased_cost"] = cost

    keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
    await update.message.reply_text(
        f"🎁 Horse {horse_number} selected for {cost:,} chips.\n\n"
        "Now reply with the recipient’s Telegram @username or numeric user ID.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return

async def catch_buy_and_gift_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    horse_number = context.user_data.pop("purchased_gift_horse", None)
    cost         = context.user_data.pop("purchased_cost", None)
    if horse_number is None or cost is None:
        await update.message.reply_text("❌ No purchase in progress to gift.")
        return

    # ─── NEW: Only accept numeric ID ───
    try:
        recipient_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "❌ That is not a valid numeric user ID. "
            "Please have the recipient run /myid and send that number. No charge was made."
        )
        return

    # 3) Look up that Player by ID
    try:
        recipient_player = await sync_to_async(Player.objects.get)(id=recipient_id)
    except Player.DoesNotExist:
        await update.message.reply_text(
            f"❌ No player in our database has ID {recipient_id}. No charge was made."
        )
        return

    try:
        await buy_horse_for_recipient_async(
            user_id, recipient_id, horse_number, cost
        )
    except HorseUnavailable:
        await update.message.reply_text(
            f"❌ Horse {horse_number} was purchased by someone else. No charge was made."
        )
        return
    except InsufficientChips:
        await update.message.reply_text(
            f"❌ You no longer have the {cost:,} chips required. No charge was made."
        )
        return

    # 5) Notify buyer
    await update.message.reply_text(
        f"🎁 You bought Horse {horse_number} for {cost:,} chips and gifted it to player‐ID {recipient_player.id}!"
    )
    # Notify recipient if possible
    try:
        await context.bot.send_message(
            chat_id=recipient_player.id,
            text=f"🎁 You have received Horse {horse_number}! Enjoy!"
        )
    except Exception:
        pass

    return



async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Reply with the sender’s numeric Telegram user ID.
    """
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your numeric user ID is: {user_id}")
    
async def catch_all_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return  # Skip updates that don't contain a message with text

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ─── 1) If we’re in “awaiting_list_horse” mode → the text is the sale price ───
    if context.user_data.get("awaiting_list_horse"):
        horse_number = context.user_data.pop("awaiting_list_horse")
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await update.message.reply_text("❌ You no longer own that horse. Aborting.")
            return

        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("❌ That is not a valid price. Aborting.")
            return

        price = int(text)

        await sync_to_async(HorseSale.objects.create)(
            horse=owned_horse,
            price=price
        )

        display_label = f"{owned_horse.name} ({horse_number})" if owned_horse.name else f"Horse {horse_number}"

        notified_users = await sync_to_async(list)(
            UserSettings.objects.filter(notify_new_sales=True).select_related("player")
        )

        for setting in notified_users:
            try:
                await context.bot.send_message(
                    chat_id=setting.player.id,
                    text=(
                        f"🛒 A new horse has been listed for sale!\n"
                        f"{display_label} — {price:,} chips\n"
                        "Check it out in the 🐎 Buy Horse menu!"
                    )
                )
            except Exception as e:
                print(f"[ERROR] Could not notify {setting.player.id}: {e}")

        await update.message.reply_text(
            f"✅ {display_label} is now listed for sale at {price:,} chips.\n"
            f"Others can buy from “Buy Horse” or “Horses on Sale.”"
        )

        return

    # ─── 2) If we’re in “awaiting_buy_horse” mode → this is a normal purchase of an unowned horse ───
    if context.user_data.get("awaiting_buy_horse"):
        # [Your existing catch_buy_horse_number logic goes here, exactly as before…]
        return await catch_buy_horse_number(update, context)

    # ─── 3) If we’re in “awaiting_buy_and_gift” mode → …
    if context.user_data.get("awaiting_buy_and_gift"):
        return await catch_buy_and_gift_number(update, context)

    # ─── 4) If we’re in “purchased_gift_horse” mode → …
    if context.user_data.get("purchased_gift_horse"):
        return await catch_buy_and_gift_recipient(update, context)

    # ─── 5) If we’re in “awaiting_set_emoji” mode → …
    if context.user_data.get("awaiting_set_emoji"):
        return await catch_set_emoji(update, context)

    # ─── 6) If we’re in “awaiting_rename_horse” mode → …
    if context.user_data.get("awaiting_rename_horse"):
        return await catch_rename_horse(update, context)

    # ─── 7) If we’re in “awaiting_gift_owned” mode → …
    if context.user_data.get("awaiting_gift_owned"):
        return await catch_gift_owned_recipient(update, context)

    # ─── 8) If we’re in “purchased_gift_horse” mode → …
    if context.user_data.get("purchased_gift_horse"):
        return await catch_buy_and_gift_recipient(update, context)

    # ─── otherwise: ignore or send a default message if you like ───
    return



async def catch_buy_horse_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_set_emoji"):
        return await catch_set_emoji(update, context)

    # Only run if they clicked “Buy Horse” and we’re waiting for a number
    if not context.user_data.get("awaiting_buy_horse"):
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()
    # Clear the “awaiting_buy_horse” flag immediately
    context.user_data.pop("awaiting_buy_horse", None)

    # 1) Validate it's numeric
    if not text.isdigit():
        await update.message.reply_text(
            "❌ That’s not a valid horse number. Aborting. ↩️ Run /horse again."
        )
        return

    horse_number = int(text)

    # 2) Reserve 1, 2, 3
    if horse_number in (1, 2, 3):
        await update.message.reply_text(
            "❌ Horse 1, 2, and 3 are reserved and cannot be purchased. ↩️ Run /horse again to pick a different number."
        )
        return
    if horse_number <= 1:
        await update.message.reply_text(
            "❌ Don't, just.... Don't. ↩️ Run /horse again to pick a different number."
        )
        return
    # 3) Check if already owned (any existing record for this number)
    exists = await sync_to_async(OwnedHorse.objects.filter)(horse_number=horse_number)
    if await sync_to_async(exists.exists)():
        await update.message.reply_text("❌ That horse number is already owned. ↩️ /horse")
        return

    # 4) Determine cost according to your rules
    s = str(horse_number)
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

    if params.buyhorse_event:
        cost = params.todays_horse_price
    else:
        if len(s) == 1:
            cost = 100_000
        elif len(s) == 2:
            cost = 120_000 if s[0] == s[1] else 80_000
        elif len(s) == 3:
            cost = 120_000 if (s[0] == s[1] == s[2]) else 60_000
        else:
            cost = 120_000 if all(ch == s[0] for ch in s) else 60_000

    # 5) Fetch player
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered. ↩️ /horse")
        return

    try:
        await buy_horse_async(user_id, horse_number, cost)
    except HorseUnavailable:
        await update.message.reply_text(
            "❌ That horse number is already owned. ↩️ /horse"
        )
        return
    except InsufficientChips:
        await update.message.reply_text(
            f"❌ You need {cost} chips to buy Horse {horse_number}, but you have {player.chips}. ↩️ /horse"
        )
        return

    await update.message.reply_text(
        f"✅ You now own Horse {horse_number}! (−{cost} chips) ↩️ Run /horse again."
    )

async def catch_set_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only run if we previously put “awaiting_set_emoji” into user_data
    print("DEBUG: in catch_set_emoji; flag =", context.user_data.get("awaiting_set_emoji"))
    if "awaiting_set_emoji" not in context.user_data:
        return

    user_id = update.effective_user.id
    horse_number = context.user_data.pop("awaiting_set_emoji")  # pop so we don't stay in this mode
    new_emoji = update.message.text.strip()
    EMOJI_COST = 9000

    # 1) Validate they sent something
    if not new_emoji:
        await update.message.reply_text(
            "❌ That’s not a valid emoji. Aborting. ↩️ Run /horse again."
        )
        return

    # 2) Fetch Player and OwnedHorse
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered. ↩️ Run /horse again.")
        return

    try:
        horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id, horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text(
            "❌ You do not own that horse. ↩️ Run /horse again."
        )
        return

    try:
        horse = await customize_horse_async(
            user_id, horse_number, EMOJI_COST, emoji=new_emoji
        )
    except InsufficientChips:
        await update.message.reply_text(
            f"❌ Not enough chips! Changing an emoji costs {EMOJI_COST}. ↩️ Run /horse again."
        )
        return

    # 5) Confirm
    await update.message.reply_text(
        f"✅ Emoji for Horse {horse_number} updated to {new_emoji}! (−{EMOJI_COST} chips)\n"
        "↩️ Run /horse again."
    )


async def catch_rename_horse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # We know here that awaiting_rename_horse is set.
    # Pop it immediately so we don’t handle the same text again.
    horse_number = context.user_data.pop("awaiting_rename_horse")

    user_id = update.effective_user.id
    new_name = update.message.text.strip()

    # 1) Fetch the OwnedHorse to confirm ownership
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id, horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You do not own that horse anymore.")
        return

    # 2) Fetch Player to check chips
    player = await sync_to_async(Player.objects.get)(id=user_id)
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)
    if params.rename_horse_event:
        cost = 1
    else:
        cost = 60_000
    try:
        await customize_horse_async(
            user_id, horse_number, cost, name=new_name
        )
    except InsufficientChips:
        await update.message.reply_text(f"❌ Not enough chips! Renaming costs {cost:,} chips.")
        return

    await update.message.reply_text(
        f"✅ Your horse #{horse_number} is now named “{new_name}”! (−{cost:,} chips)"
    )
async def richest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) Fetch top 5 players ordered by chips descending
    top_players = await sync_to_async(list)(
        Player.objects.order_by("-chips")[:5]
    )
    if not top_players:
        await update.message.reply_text("ℹ️ No players found in the database yet.")
        return

    # 2) Build a praise‐filled message
    lines = ["🏆 *Top 5 Richest Players* 🏆\n"]
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]  # first three special, others identical

    for idx, player in enumerate(top_players, start=1):
        medal = medals[idx - 1]
        name = player.name or f"User {player.id}"
        chips = f"{player.chips:,}"
        lines.append(f"{medal} *{name}* — {chips} chips")

    lines.append("\n🎉 Congratulations to our Unemployed Friends! 🎉")
    text = "\n".join(lines)

    # 3) Send with Markdown formatting
    await update.message.reply_text(text, parse_mode="Markdown")









@sync_to_async
def get_top_referrers_fixed():
    # Annotate each player with:
    # 1. Count of players that reference them as referrer
    # 2. Sum of referral earnings
    return list(
        Player.objects.annotate(
            referred_count=Count("referred_friends", distinct=True),
            total_earned=Sum("referral_earnings__amount")
        )
        .filter(referred_count__gt=0)
        .order_by("-referred_count", "-total_earned")[:5]
    )

async def referral_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_referrers = await get_top_referrers_fixed()

    if not top_referrers:
        await update.message.reply_text("No referral data yet.")
        return

    text = "🏆 *Top Referrers*\n\n"
    for idx, player in enumerate(top_referrers, start=1):
        text += (
            f"*{idx}. {player.name}*\n"
            f"👥 Brought: {player.referred_count} users\n"
            f"💰 Earned: {player.total_earned or 0:,} chips\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")



async def teachme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🃏 *راهنمای بازی کلاسیک بلک‌جک*\n\n"
        "بلک‌جک همون بازی معروف «۲۱» هست. 🎯\n"
        "هدف اینه که جمع کارت‌هات دقیقاً بشه ۲۱ یا حداقل خیلی بهش نزدیک باشه.\n\n"
        "🕹️ بازی ۵ راند داره. هر راند، بازیکنی که دست بالاتری داشته باشه، اون راند رو می‌بره.\n"
        "در پایان، کسی که بیشترین راند رو برده باشه، کل پولِ روی میز رو می‌بره. 💰\n\n"
        "✅ برای شروع بازی:\n"
        "• با دستور `/startblackjack` بازی رو استارت می‌زنیم\n"
        "• بعد، مبلغ شرط رو انتخاب می‌کنیم\n"
        "• با دستور `/join` وارد بازی می‌شیم\n"
        "• وقتی همه جوین شدن، با `/forcestart` بازی رو شروع می‌کنیم\n\n"
        "✉️ بعد از شروع، ربات به پیوی شما دو تا کارت می‌فرسته. مثلاً:\n"
        "`🃏 Your hand: [10, 'Q']`\n"
        "`♠️ Total value: 20`\n\n"
        "⏳ وقتی نوبت شما بشه، ربات بهتون این پیام رو می‌ده:\n"
        "`Hirbod, it's your turn!`\n"
        "`Type /hit 🎰 to draw a card`\n"
        "`or /stand❗️ to keep your hand`\n"
        "وقتی این پیام رو دیدید (اسم شما جای Hirbod میاد)، دو تا انتخاب دارید:\n"
        "`/hit` یا `/stand`\n\n"
        "🎰 *توضیح /hit:*\n"
        "وقتی می‌خواید کارت بکشید، از این دستور استفاده می‌کنید.\n"
        "مثلاً اگه دستتون این باشه:\n"
        "`🃏 Your hand: [4, 5]`\n"
        "`♠️ Total value: 9`\n"
        "با ۹ که قطعاً نمی‌تونید برنده شید، پس کارت می‌کشید تا به عددهایی مثل ۱۹، ۲۰ یا خود ۲۱ برسید.\n\n"
        "🛑 *توضیح /stand:*\n"
        "وقتی دستتون مثلاً ۱۸ یا ۱۹ یا ۲۰ شد، اگر اهل ریسک نیستید می‌تونید همون‌جا `/stand` بزنید.\n"
        "یعنی اعلام کنید که دیگه کارت نمی‌خواید و نوبت نفر بعدی بشه.\n"
        "تا آخر راند هم با همین دست جلو می‌رید.\n"
        "ولی اگر اهل ریسک باشید، یه کارت دیگه می‌کشید تا شاید به ۲۱ برسید!\n\n"
        "🏁 اگر دست شما از بقیه بهتر باشه، اون راند رو می‌برید.\n"
        "کسی که بیشترین راند رو برده باشه، برنده کل بازی میشه.\n\n"
        "🤖 یه ربات هم داخل بازی هست به‌عنوان دیلر (نماینده کازینو) که کارت‌ها رو پخش می‌کنه و خودش هم بازی می‌کنه.\n"
        "📌 اگر با دیلر مساوی کنید، دیلر می‌بره.\n"
        "مثال:\n"
        "`🃏 Your hand: [10, 'Q']`\n"
        "`♠️ Total value: 20`\n"
        "`🤖 Dealer stands with a total of 20`\n"
        "`🤖 Dealer wins🥇 this round!`\n\n"
        "🂡 *توضیح کارت‌ها:*\n"
        "• K (کینگ)، Q (کویین)، J (سرباز) = همشون ارزششون ۱۰ هست\n"
        "• A (آس) = می‌تونه ۱ یا ۱۱ باشه (بسته به شرایط دست شما)\n\n"
        "مثلاً:\n"
        "`🃏 Your hand: ['A', 9]`\n"
        "`♠️ Total value: 20`\n"
        "حالا اگه یه کارت دیگه بکشید مثلاً ۵:\n"
        "`🃏 Your hand: ['A', 9, 5]`\n"
        "`♠️ Total value: 15`\n"
        "چون A خودش رو از ۱۱ به ۱ تغییر داده تا دست شما نسوزه.\n\n"

    )
    await update.message.reply_text(text, parse_mode="Markdown")
