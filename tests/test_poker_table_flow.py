"""Drive the in-group poker table through its buttons with a fake bot."""

import asyncio
from itertools import count
from unittest import mock

from django.test import TestCase

from game.models import Dealer, Player, PokerHand, PokerSeat, PokerTable
from game.telegram import poker


class FakeBot:
    def __init__(self):
        self.ids = count(1000)
        self.sent = []
        self.edits = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        return mock.Mock(message_id=next(self.ids))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)

    async def delete_message(self, *args, **kwargs):
        pass


def press(data, user_id, chat_id=-9100):
    query = mock.Mock()
    query.data = data
    query.from_user.id = user_id
    query.message.chat.id = chat_id
    query.message.chat.type = "supergroup"
    query.answer = mock.AsyncMock()
    query.message.delete = mock.AsyncMock()
    update = mock.Mock(callback_query=query, effective_user=query.from_user, effective_chat=query.message.chat)
    return update, query


class PokerTableFlowTests(TestCase):
    def setUp(self):
        self.alice = Player.objects.create(id=7101, name="Alice", chips=10_000)
        self.bob = Player.objects.create(id=7102, name="Bob", chips=10_000)
        Dealer.objects.create(chips=100_000)
        self.bot = FakeBot()
        self.context = mock.Mock(bot=self.bot)
        patcher = mock.patch.multiple(poker, FIRST_DEAL_SECONDS=0, NEXT_DEAL_SECONDS=3600)
        patcher.start()
        self.addCleanup(patcher.stop)
        lang = mock.patch.object(poker, "language_for_update", mock.AsyncMock(return_value="en"))
        lang.start()
        self.addCleanup(lang.stop)

    async def click(self, data, user_id):
        update, query = press(data, user_id)
        await poker.poker_callback(update, self.context)
        return query

    async def settle_tasks(self):
        for _ in range(5):
            await asyncio.sleep(0)
        for tasks in (poker._deal_tasks, poker._turn_tasks):
            for task in list(tasks.values()):
                task.cancel()
            tasks.clear()

    async def test_create_sit_autodeal_and_play_to_the_end_through_buttons(self):
        await self.click("poker:create:500:5", self.alice.pk)
        table = await PokerTable.objects.aget(chat_id=-9100)
        await self.click(f"poker:sit:{table.pk}", self.bob.pk)
        for _ in range(50):  # FIRST_DEAL_SECONDS=0 → the deal task fires
            await asyncio.sleep(0.01)
            if any("your turn" in text for text in self.bot.sent):
                break
        hand = await PokerHand.objects.aget(table=table)
        self.assertTrue(any("your turn" in text for text in self.bot.sent))

        # Peeking shows cards privately.
        peek = await self.click(f"poker:cards:{table.pk}", self.alice.pk)
        self.assertIn("🂡", peek.answer.await_args.args[0])

        # The wrong player is refused; the right one acts until the hand ends.
        for _ in range(12):
            await hand.arefresh_from_db()
            if hand.phase == PokerHand.Phase.COMPLETE:
                break
            seat = await PokerSeat.objects.select_related("player").aget(table=table, seat_number=hand.current_seat)
            other = self.bob.pk if seat.player_id == self.alice.pk else self.alice.pk
            refused = await self.click(f"poker:act:{hand.pk}:check", other)
            self.assertTrue(refused.answer.await_args.kwargs.get("show_alert"))
            move = "call" if hand.current_bet > seat.committed_round else "check"
            await self.click(f"poker:act:{hand.pk}:{move}", seat.player_id)
        self.assertEqual(hand.phase, PokerHand.Phase.COMPLETE)
        self.assertIn("RESULT", self.bot.edits[-1] if self.bot.edits else self.bot.sent[-1])

        # Leaving between hands cashes out at once.
        leave = await self.click(f"poker:leave:{table.pk}", self.bob.pk)
        self.assertIn("left with", leave.answer.await_args.args[0])
        await self.settle_tasks()
        total = sum([s async for s in PokerSeat.objects.filter(table=table).values_list("stack", flat=True)])
        await self.alice.arefresh_from_db()
        await self.bob.arefresh_from_db()
        self.assertEqual(self.alice.chips + self.bob.chips + total, 20_000)
