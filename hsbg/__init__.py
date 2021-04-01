"""A simulator for Hearthstone Battlegrounds."""
from __future__ import annotations
import random
from enum import IntEnum
from contextlib import contextmanager
from typing import List, Optional, Dict

from hsbg.utils import filter_minions
from hsbg.minions import MinionPool
from hsbg.combat import Battle, simulate_combat


# The maximum number of minions a player can have in their hand.
MAX_HAND_SIZE = 10
# The maximum number of minions that can be on the board in a tavern.
MAX_TAVERN_BOARD_SIZE = 7
# The number of recruits to offer the player at the start of the game.
INITIAL_NUM_RECRUITS = 3
# A list mapping each tavern tier to the additional number of recruits gained at that tier.
# The element at index i indicates the additional recruits gained after upgrading FROM tier i.
RECRUIT_NUM_PROGRESSION = [
    0,  # Padding element
    1,  # One new recruit after upgrading from tier 1
    0,  # No new recruit after upgrading from tier 2
    1,  # One new recruit after upgrading from tier 3
    0,  # No onew recruit after upgrading from tier 4
    1  # One new recruit after upgrading from tier 5
]
# The amount of gold a refresh costs.
TAVERN_REFRESH_COST = 1
# The maximum number of recruits that can be on the board in a tavern.
MAX_TAVERN_RECRUIT_SIZE = 6
# The maximum number of gold the player can have.
MAX_TAVERN_GOLD = 10
# The amount of gold the player gets per turn.
GOLD_PER_TURN = 1
# The amount of gold you start with
STARTING_GOLD = 3

# A list mapping each tavern tier to its upgrade cost.
# The element at index i indicates the cost of upgrading FROM a tavern with tier i.
TAVERN_UPGRADE_COSTS = [
    0,  # Padding element
    5,  # Cost of upgrading from tier 1 (5 gold)
    7,  # Cost of upgrading from tier 2 (7 gold)
    8,  # Cost of upgrading from tier 3 (8 gold)
    9,  # Cost of upgrading from tier 4 (9 gold)
    10  # Cost of upgrading from tier 5 (10 gold)
]
# The maximum tavern tier
MAX_TAVERN_TIER = 6

# Minion buy and sell price
TAVERN_MINION_BUY_PRICE = 3
TAVERN_MINION_SELL_PRICE = 1


class TavernGameBoard:
    """A class representing the state of a tavern game board for a single player.
    Note: the game board starts at turn 0!
    """
    # Private Instance Attributes:
    #   - _turn_number: The current turn (where 1 indicates the first turn).
    #   - _hero_health: The current health of the hero.
    #   - _tavern_tier: The current tier of the tavern.
    #   - _gold: The current gold that the player has.
    #   - _hand: A list of minions in the hand.
    #   - _board: A list of minions on the board.
    #   - _pool: The pool of minions to select recruits from.
    #   - _num_recruits: The number of recruits offered to the player currently.
    #   - _recruits: A list of current recruits.
    #   - _is_frozen: Whether the recruit selection is currently frozen.
    #   - _max_freeze_times: The maximum number of times freeze can be toggled in a turn.
    #   - _times_frozen: The number of times freeze has been toggled this turn.
    #   - _refresh_cost: The current cost of refreshing the recruitment pool.
    #   - _refresh_cost_clock: Clock to manage when to change the refresh cost.
    #   - _tavern_upgrade_discount: A discount applied to the next tavern upgrade.
    #   - _tavern_upgrade_discount_clock: Clock to manage when to change the tavern upgrade cost discount.
    #   - _minion_buy_price: The amount of gold it costs to buy a minion.
    #   - _minion_sell_price: The amount of gold the player gets when they sell a minion.
    #   - _battle_history: A history of the battles between this board and enemy boards,
    #                      ordered by time of battle.
    _turn_number: int
    _hero_health: int
    _tavern_tier: int
    _gold: int
    _hand: List[Optional[Minion]]
    _board: List[Optional[Minion]]
    _pool: MinionPool

    _num_recruits: int
    _recruits: List[Optional[Minion]]
    _is_frozen: bool
    _max_freeze_times: Optional[int]
    _times_frozen: int

    _refresh_cost: int
    _refresh_cost_clock: Optional[TurnClock]

    _tavern_upgrade_discount: int
    _tavern_upgrade_discount_clock: Optional[TurnClock]

    _minion_buy_price: int
    _minion_sell_price: int

    _battle_history: List[Battle]

    def __init__(self, pool: Optional[MinionPool] = None, hero_health: int = 40,
                 tavern_tier: int = 1, max_freeze_times: Optional[int] = None) -> None:
        """Initialise the TavernGameBoard.

        Args:
            pool: The pool of minions to select recruits from.
            hero_health: The starting health of the hero.
            tavern_tier: The starting tier of the tavern.
            max_freeze_times: The maximum number of times freeze can be toggled in a turn.
        """
        self._turn_number = 0
        self._hero_health = hero_health
        self._tavern_tier = tavern_tier
        self._gold = 0

        self._hand = [None] * MAX_HAND_SIZE
        self._board = [None] * MAX_TAVERN_BOARD_SIZE
        self._pool = pool or MinionPool()

        self._num_recruits = INITIAL_NUM_RECRUITS
        self._recruits = [None] * MAX_TAVERN_RECRUIT_SIZE

        self._is_frozen = False
        self._max_freeze_times = max_freeze_times
        self._times_frozen = 0

        self._reset_refresh_cost()
        self._reset_tavern_upgrade_discount()

        self._minion_buy_price = TAVERN_MINION_BUY_PRICE
        self._minion_sell_price = TAVERN_MINION_SELL_PRICE

        self._battle_history = []

    def next_turn(self) -> None:
        """Reset the tavern to the start of the next turn.

        >>> board = TavernGameBoard()
        >>> board.next_turn()
        >>> board.turn_number == 1
        True
        >>> board._spend_gold(3)
        True
        >>> board.gold == 0
        True
        >>> board.next_turn()
        >>> board.turn_number == 2
        True
        >>> board.gold == 4
        True
        """
        if self._turn_number > 0:
            # Call the end turn events
            self._handle_on_end_turn()

        self._turn_number += 1
        self._gold = min((self._turn_number - 1) * GOLD_PER_TURN + STARTING_GOLD, MAX_TAVERN_GOLD)
        self._refresh_recruits()
        if self._is_frozen:
            self._is_frozen = False
        self._times_frozen = 0

        # Call the new turn events
        self._handle_on_new_turn()

    def _handle_on_new_turn(self):
        """Call the _on_new_turn event on minions in the hand and on the board."""
        minions = self._hand + self._board
        for x in minions:
            if x is None:
                continue
            x.on_new_turn(self)

    def _handle_on_end_turn(self):
        """Call the _on_end_turn event on minions in the hand and on the board."""
        minions = self._hand + self._board
        for x in minions:
            if x is None:
                continue
            x.on_end_turn(self)

    def _refresh_recruits(self) -> bool:
        """Refresh the selection of recruits without spending gold.
        Do nothing if the selection is frozen. Return whether the recruits were refreshed.
        """
        if self._is_frozen:
            return False

        # Insert non-None minions back into the pool.
        self._pool.insert([minion for minion in self._recruits if minion is not None])
        # Roll new minions from pool
        minions = self._pool.get_random(n=self._num_recruits, max_tier=self._tavern_tier)
        # Fill recruit list from left to right
        for i, minion in enumerate(minions):
            self._recruits[i] = minion
        return True

    def refresh_recruits(self) -> bool:
        """Refresh the selection of recruits. Do nothing if the selection is frozen,
        or if the player does not have enough gold. Return whether the recruits were refreshed.

        >>> board = TavernGameBoard()
        >>> board.refresh_recruits()  # No turns have been started, so we have 0 gold!
        False
        >>> board.next_turn()
        >>> board.refresh_recruits()
        True
        >>> board.gold == 2
        True
        >>> board.next_turn()
        >>> board.freeze()
        True
        >>> board.refresh_recruits()
        False
        """
        if not self._can_spend_gold(self._refresh_cost):
            # We can't refresh since we don't have enough gold!
            return False
        if not self._refresh_recruits():
            # The refresh was not successful!
            return False

        # The refresh was successful so subtract the amount from the gold total.
        self._spend_gold(self._refresh_cost)

        # Update refresh cost
        if self._refresh_cost_clock is not None:
            self._refresh_cost_clock.step()

        return True

    def set_refresh_cost(self, amount: int, times: Optional[int] = 1) -> None:
        """Set the recruit refresh cost.

        Args:
            amount: The new cost of refreshing the recruitment pool.
            turns: The amount of times to keep this cost.
                   If None, then the new refresh cost is indefinite.

        >>> board = TavernGameBoard()
        >>> board.set_refresh_cost(10, times=1)
        >>> board.refresh_cost
        10
        >>> board.give_gold(10)
        >>> board.refresh_recruits()
        True
        >>> board.refresh_cost
        1
        """
        self._refresh_cost = amount
        if times is not None:
            self._refresh_cost_clock = TurnClock(times, on_complete=self._reset_refresh_cost)

    def _reset_refresh_cost(self) -> None:
        """Reset the refresh cost to the default value. This also clears the refresh cost clock."""
        self._refresh_cost = TAVERN_REFRESH_COST
        self._refresh_cost_clock = None

    def upgrade_tavern(self, apply_discount: bool = True) -> bool:
        """Upgrade the tavern. Do nothing if the tavern cannot be upgraded anymore,
        or if the player does not have enough gold. Return whether the upgrade was successful.

        >>> board = TavernGameBoard()
        >>> board.next_turn()
        >>> board.upgrade_tavern()  # Not enough gold (we only have 3)!
        False
        >>> board.tavern_tier == 1
        True
        >>> for _ in range(2):
        ...     board.next_turn()
        >>> board.upgrade_tavern()  # We now have 5 gold
        True
        >>> board.tavern_tier == 2
        True
        >>> board._num_recruits == 4
        True
        >>> board.gold == 0
        True
        """
        if self._tavern_tier == MAX_TAVERN_TIER:
            # We can't upgrade since we already have the max tier!
            return False

        if not self._spend_gold(self.get_tavern_upgrade_cost(apply_discount)):
            # We can't upgrade since we don't have enough gold!
            return False

        self._num_recruits += RECRUIT_NUM_PROGRESSION[self._tavern_tier]
        self._tavern_tier += 1

         # Update discount
        if self._tavern_upgrade_discount_clock is not None:
            self._tavern_upgrade_discount_clock.step()

        return True

    def get_tavern_upgrade_cost(self, apply_discount: bool = True) -> int:
        """Return the current cost of upgrading the tavern."""
        discount = self._tavern_upgrade_discount if apply_discount else 0
        return max(TAVERN_UPGRADE_COSTS[self._tavern_tier] - discount, 0)

    def set_tavern_upgrade_discount(self, amount: int, times: Optional[int] = 1) -> None:
        """Set a discount for the cost of the next tavern upgrades.

        Args:
            amount: The discount applied to the tavern upgrade cost.
            turns: The amount of times to apply the discount.
                   If None, then the discount is applied infinitely many times.

        >>> board = TavernGameBoard()
        >>> board.set_tavern_upgrade_discount(10, times=2)
        >>> board.upgrade_tavern()  # Free since the first upgrade costs 5 gold.
        True
        >>> board.upgrade_tavern()  # Free since the second upgrade costs 7 gold.
        True
        >>> board.upgrade_tavern()
        False
        """
        self._tavern_upgrade_discount = amount
        if times is not None:
            clock = TurnClock(times, on_complete=self._reset_tavern_upgrade_discount)
            self._tavern_upgrade_discount_clock = clock

    def _reset_tavern_upgrade_discount(self) -> None:
        """Reset the tavern upgrade cost discount to the default value.
        This also clears the tavern upgrade discount clock.
        """
        self._tavern_upgrade_discount = 0
        self._tavern_upgrade_discount_clock = None

    def freeze(self) -> bool:
        """Freeze the selection of recruit minions. Do nothing if the number of times frozen
        exceeds the limit, or if the recruits are already frozen.

        Return whether the recruits could be frozen.

        >>> board = TavernGameBoard()
        >>> board.next_turn()
        >>> previous_recruits = list(board._recruits)
        >>> board.next_turn()
        >>> previous_recruits == board._recruits
        False
        >>> board.freeze()
        True
        >>> board.is_frozen
        True
        >>> previous_recruits = list(board._recruits)
        >>> board.next_turn()
        >>> previous_recruits == board._recruits
        True
        >>> board = TavernGameBoard(max_freeze_times=1)
        >>> board.freeze()
        True
        >>> board.freeze()
        False
        >>> board.unfreeze()
        True
        >>> board.freeze()
        False
        >>> board.next_turn()
        >>> board.freeze()
        True
        """
        past_limit = self._max_freeze_times is not None and self._times_frozen >= self._max_freeze_times
        if self._is_frozen or past_limit:
            return False

        self._times_frozen += 1
        self._is_frozen = True
        return True

    def unfreeze(self) -> bool:
        """Unfreeze the selection of recruit minions. Do nothing if the recruits are not frozen.
        Return whther the recruits could be unfrozen.

        >>> board = TavernGameBoard()
        >>> board.freeze()
        True
        >>> board.unfreeze()
        True
        >>> board.is_frozen
        False
        """
        if not self._is_frozen:
            return False

        self._is_frozen = False
        return True

    def attack_hero(self, damage: int) -> None:
        """Attack the tavern hero with the given amount of damage.

        >>> board = TavernGameBoard()  # Initialise board with 40 health!
        >>> board.attack_hero(10)
        >>> board.hero_health
        30
        """
        self._hero_health -= damage

    @property
    def is_dead(self) -> bool:
        """Return whether the hero is dead.

        >>> board = TavernGameBoard()  # Initialise board with 40 health!
        >>> board.attack_hero(31)
        >>> board.is_dead
        False
        >>> board.attack_hero(20)
        >>> board.is_dead
        True
        """
        return self._hero_health <= 0

    def _can_spend_gold(self, amount: int) -> bool:
        """Return whether the given amount of gold can be spent.

        Preconditions:
            - amount >= 0

        >>> board = TavernGameBoard()
        >>> board._can_spend_gold(1)  # No turns have been started, so we have 0 gold!
        False
        >>> board.next_turn()  # We have 3 gold
        >>> board._can_spend_gold(100)
        False
        >>> board._can_spend_gold(1)
        True
        """
        return self._gold >= amount

    def _spend_gold(self, amount: int) -> bool:
        """Return whether the given amount of gold can be spent. If it can be,
        mutate the TavernGameBoard by subtracting that amount from the current gold total.

        Preconditions:
            - amount >= 0

        >>> board = TavernGameBoard()
        >>> board._spend_gold(1)  # No turns have been started, so we have 0 gold!
        False
        >>> board.next_turn()  # We have 3 gold
        >>> board._spend_gold(100)
        False
        >>> board.gold == 3
        True
        >>> board._spend_gold(3)
        True
        >>> board.gold == 0
        True
        """
        if not self._can_spend_gold(amount):
            return False

        self._gold -= amount
        return True

    def give_gold(self, amount: int) -> None:
        """Give the player gold.

        Preconditions:
            - amount >= 0

        >>> board = TavernGameBoard()
        >>> board.give_gold(5)
        >>> board.gold == 5
        True
        >>> board.give_gold(4)
        >>> board.gold == 9
        True
        >>> board.give_gold(10)  # Max gold is 10
        >>> board.gold == 10
        True
        """
        self._gold = min(self._gold + amount, MAX_TAVERN_GOLD)

    def buy_minion(self, index: int) -> bool:
        """Buy the minion (recruit) at the given index. Return whether the minion could be bought.
        Do nothing if there is no minion at the given index, or if there is not enough gold.

        >>> board = TavernGameBoard()
        >>> board.next_turn()
        >>> minion = board.recruits[0]
        >>> board.buy_minion(0)
        True
        >>> board.hand[0] == minion
        True
        >>> board.recruits[0] is None
        True
        >>> board.gold == 0
        True
        >>> board.buy_minion(1)
        False
        >>> board.next_turn()
        >>> board.buy_minion(4)  # We only have 3 available recruits
        False
        >>> board.buy_minion(100)  # Index is out of range
        False
        >>> board.gold == 4
        True
        """
        if index < 0 or index >= len(self.recruits) or self._recruits[index] is None:
            return False

        minion = self._recruits[index]
        if not self._spend_gold(self._minion_buy_price):
            # We can't buy the minion since we don't have enough gold!
            return False

        self._recruits[index] = None
        if not self.add_minion_to_hand(minion, clone=False):
            return False

        minion.on_this_bought(self)
        return True

    def add_minion_to_hand(self, minion: Minion, index: Optional[int] = None, clone: bool = True) \
            -> bool:
        """Add the given minion to the hand. Return whether the minion could be added to the hand.

        Args:
            index: The index to place the minion. If None, places the minion at the right-most
                   available position (i.e. the first index in the hand that is empty).
            clone: Whether to clone the minion before adding it to hand.
                   Note that the cloned minion does NOT keep the buffs of the original.

        >>> board = TavernGameBoard()
        >>> minion = board.pool.find(name='Murloc Tidehunter')
        >>> all(x is None for x in board.hand)  # Empty hand
        True
        >>> board.add_minion_to_hand(minion)
        True
        >>> board.hand[0] == minion
        True
        >>> minion = board.pool.find(name='Vulgar Homunculus')
        >>> board.add_minion_to_hand(minion, index=3)
        True
        >>> board.hand[3] == minion
        True
        >>> board.add_minion_to_hand(minion, index=3)  # There is already a minion here
        False
        >>> board.add_minion_to_hand(minion, index=10)  # This index is out of range
        False
        """
        if index is not None and (index < 0 or index >= len(self._hand) \
                                  or self._hand[index] is not None):
            # We can't add the minion to hand since the index is out of range,
            # or the given index is not empty.
            return False

        if index is None:
            try:
                # Find the first element in the list that is None
                index = self._hand.index(None)
            except ValueError:
                # None could not be found in the list. The hand is full!
                return False

        if clone:
            minion = minion.clone()

        self._hand[index] = minion
        return True

    def sell_minion(self, index: int) -> bool:
        """Sell the minion on the board at the given index. Do nothing if there is no minion on the
        board at the given index. Return whether the minion could be sold.

        >>> board = TavernGameBoard()
        >>> board.next_turn()
        >>> board.buy_minion(0) and board.play_minion(0)  # We have 0 gold after buying
        True
        >>> board.sell_minion(0)
        True
        >>> board.gold == 1
        True
        >>> board.board[0] is None
        True
        >>> board.sell_minion(1)  # Empty position
        False
        >>> board.sell_minion(100)  # Out of range
        False
        """
        if index < 0 or index >= len(self._board) or self._board[index] is None:
            return False

        minion = self._board[index]
        self._board[index] = None
        self._pool.insert(minion)
        self.give_gold(self._minion_sell_price)
        minion.on_this_sold(self)

        return True

    def play_minion(self, index: int, board_index: Optional[int] = None, call_events: bool = True)\
            -> bool:
        """Play the minion from the hand at the given index. Do nothing if there is no minion in
        the hand at the given index, or if the board is full. Return whether the minion could be played.

        Args:
            index: The index of the minion to play from the hand.
            board_index: The index on the board to place the minion. If None, out of range, or the
                         given index refers to a non-empty position on the board then the first
                         empty position is used instead.
            call_events: Whether to call events on the played minion.

        >>> board = TavernGameBoard()
        >>> for _ in range(10):  # Go to turn 10 so we have 10 gold.
        ...     board.next_turn()
        >>> recruits = list(board.recruits)
        >>> all(board.buy_minion(i) for i in range(3))  # Buy all recruits
        True
        >>> board.play_minion(0)
        True
        >>> board.board[0].name == recruits[0].name
        True
        >>> board.play_minion(1, board_index=4)  # Empty position
        True
        >>> board.board[4].name == recruits[1].name
        True
        >>> board.play_minion(2, board_index=4)  # Non-empty position
        True
        >>> board.board[1].name == recruits[2].name
        True
        >>> board.play_minion(5)  # No minion in the hand at that index
        False
        >>> board.play_minion(100)  # Out of range
        False
        """
        if index < 0 or index >= len(self._hand) or self._hand[index] is None:
            # We can't add the minion to hand since the index is out of range,
            # or the given index refers to an empty position.
            return False

        minion = self._hand[index]
        self._hand[index] = None
        self.summon_minion(minion, board_index, clone=False, call_events=False)

        # Call events
        if call_events:
            minion.on_this_played(self)
            self._handle_on_any_played(minion)

        return True

    def summon_minion(self, minion: Minion, index: Optional[int] = None, clone: bool = True,
                      call_events: bool = True) -> bool:
        """Summon the given minion onto the board at the given index. Do nothing if the board is full.
        Return whether the minion could be summoned.

        Args:
            minion: The minion to summon.
            index: The index on the board to place the minion. If None, out of range, or the
                   given index refers to a non-empty position on the board then the first
                   empty position is used instead.
            clone: Whether to clone the minion before summoning it. Note that the cloned minion
                   does NOT keep any buffs.
            call_events: Whether to call events on the summoned minion.
        """
        if index is None or index < 0 or index >= len(self._board) \
                         or self._board[index] is not None:
            # The board index is None, out of range, or refers to a non-empty position.
            # Use the first non-empty position instead.
            try:
                # Find the first element in the list that is None
                index = self._board.index(None)
            except ValueError:
                # None could not be found in the list. The board is full!
                return False

        if clone:
            minion = minion.clone()

        self._board[index] = minion
        if call_events:
            minion.on_this_summoned(self)
            self._handle_on_any_summoned(minion)

        return True

    def remove_minion_from_board(self, index: int) -> Optional[Minion]:
        """Remove the minion on the board at the given index. Do nothing if there is no minion at
        the given index, or if the index is out of range.

        Return the minion that was removed, or None if the removal was not successful.

        >>> board = TavernGameBoard()
        >>> minion_a = board.pool.find(name='Murloc Scout')
        >>> minion_b = board.pool.find(name='Tabbycat')
        >>> board.summon_minion(minion_a)
        True
        >>> board.summon_minion(minion_b)
        True
        >>> board.remove_minion_from_board(0) == minion_a
        True
        >>> board.board[0] is None
        True
        >>> board.remove_minion_from_board(1) == minion_b
        True
        >>> board.board[1] is None
        True
        >>> board.remove_minion_from_board(2) is None  # Empty position
        True
        >>> board.remove_minion_from_board(10) is None  # Out of range
        True
        """
        if index < 0 or index >= len(self._board) or self._board[index] is None:
            # The index is out of range or refers to a non-empty position.
            # Use the first non-empty position instead.
            return None

        minion = self._board[index]
        self._board[index] = None
        return minion

    def _handle_on_any_played(self, played_minion: Minion) -> None:
        """Call the _on_any_played event on minions in the hand and on the board."""
        minions = self._hand + self._board
        for x in minions:
            if x is None:
                continue
            x.on_any_played(self, played_minion)

    def _handle_on_any_summoned(self, summoned_minion: Minion) -> None:
        """Call the _on_any_summoned event on minions in the hand and on the board."""
        minions = self._hand + self._board
        for x in minions:
            if x is None:
                continue
            x.on_any_summoned(self, summoned_minion)

    def get_minions_on_board(self, clone: bool = False, ignore: Optional[List[Minion]] = None,
                             **kwargs) -> List[Minion]:
        """Find all the minions on the board matching the given keyword arguments.
        Each keyword argument should be an attribute of the Minion class.

        Args:
            clone: Whether to clone the minions.
            ignore: A list of minions to ignore.
            **kwargs: Keyword arguments corresponding to minion attributes to match.

        >>> board = TavernGameBoard()
        >>> minion_a = board.pool.find(name='Murloc Scout')
        >>> minion_b = board.pool.find(name='Tabbycat', is_golden=True)
        >>> board.add_minion_to_hand(minion_a) and board.add_minion_to_hand(minion_b)
        True
        >>> board.play_minion(0) and board.play_minion(1)
        True
        >>> board.get_minions_on_board() == [minion_a, minion_b]
        True
        >>> board.get_minions_on_board(is_golden=True) == [minion_b]
        True
        >>> board.get_minions_on_board(name='Eamon Ma') == []
        True
        >>> board.get_minions_on_board(ignore=[minion_a]) == [minion_b]
        True
        """
        ignore = ignore or []
        minions = [x for x in self.board if x is not None and x not in ignore]
        return filter_minions(minions, clone=clone, **kwargs)

    def get_random_minions_on_board(self, n, clone: bool = False,
                                    ignore: Optional[List[Minion]] = None, **kwargs) \
            -> List[Minion]:
        """Get a list of random minions on the board matching the given keyword arguments.
        Each keyword argument should be an attribute of the Minion class.

        Args:
            n: The number of minions to get.
            clone: Whether to clone the minions.
            ignore: A list of minions to ignore.
            **kwargs: Keyword arguments corresponding to minion attributes to match.

        >>> board = TavernGameBoard()
        >>> minion_a = board.pool.find(name='Murloc Scout')
        >>> minion_b = board.pool.find(name='Tabbycat', is_golden=True)
        >>> board.add_minion_to_hand(minion_a) and board.add_minion_to_hand(minion_b)
        True
        >>> board.play_minion(0) and board.play_minion(1)
        True
        >>> random.seed(69)  # Use seed to get the same results everytime!
        >>> board.get_random_minions_on_board(2) == [minion_a, minion_b]
        True
        >>> board.get_random_minions_on_board(1) == [minion_a]
        True
        """
        minions = self.get_minions_on_board(clone=clone, ignore=ignore, **kwargs)
        return random.sample(minions, k=min(n, len(minions)))

    def get_random_minion_on_board(self, clone: bool = False,
                                    ignore: Optional[List[Minion]] = None, **kwargs) -> Minion:
        """Get a random minion on the board matching the given keyword arguments.
        Each keyword argument should be an attribute of the Minion class.

        If no minion could be found, then return None.

        Note: this is the same the get_random_minions_on_board function, but returns a
              single Minion object instead of a list of Minion objects.

        Args:
            clone: Whether to clone the minions.
            ignore: A list of minions to ignore.
            **kwargs: Keyword arguments corresponding to minion attributes to match.
        """
        matches = self.get_random_minions_on_board(n=1, clone=clone, ignore=ignore, **kwargs)
        if len(matches) == 0:
            return None
        else:
            return matches[0]

    def get_index_of_minion_on_board(self, minion: Minion) -> Optional[int]:
        """Return the board index of the given minion. If there are duplicate minions,
        this returns the index of the leftmost duplicate.

        Return None if the minion could not be found.

        >>> board = TavernGameBoard()
        >>> minion_a = board.pool.find(name='Murloc Scout')
        >>> minion_b = board.pool.find(name='Tabbycat')
        >>> board.summon_minion(minion_a)
        True
        >>> board.summon_minion(minion_b)
        True
        >>> board.summon_minion(minion_a)
        True
        >>> board.get_index_of_minion_on_board(minion_a)
        0
        >>> board.get_index_of_minion_on_board(minion_b)
        1
        >>> minion_c = board.pool.find(name='Alleycat')
        >>> board.get_index_of_minion_on_board(minion_c) is None
        True
        """
        try:
            return self.board.index(minion)
        except ValueError:
            return None

    def battle(self, enemy_board: TavernGameBoard) -> Battle:
        """Battle with the given enemy board. Return the battle statistics."""
        battle = simulate_combat(self, enemy_board, n=1)
        # Update hero health
        self._hero_health = int(battle.expected_hero_health)
        enemy_board._hero_health = int(battle.expected_enemy_hero_health)

        # Save history
        self._battle_history.append(battle)
        enemy_board._battle_history.append(battle.invert())
        return battle

    def get_valid_moves(self) -> List[Move]:
        """Return a list of valid moves."""
        # We can always end the turn or freeze
        moves = [Move(Action.END_TURN), Move(Action.FREEZE)]
        if self.gold >= self.get_tavern_upgrade_cost():
            moves.append(Move(Action.UPGRADE))
        if self.gold >= self.refresh_cost:
            moves.append(Move(Action.REFRESH))

        # Add buy minion moves
        if self.gold >= self._minion_buy_price:
            for index, minion in enumerate(self.recruits):
                if minion is not None:
                    moves.append(Move(Action.BUY_MINION, index))
        # Add sell minion moves
        for index, minion in enumerate(self.board):
            if minion is not None:
                moves.append(Move(Action.SELL_MINION, index))
        # Add play minion moves
        for index, minion in enumerate(self.hand):
            if minion is not None:
                moves.append(Move(Action.PLAY_MINION, index))
        return moves

    @property
    def won_previous(self) -> bool:
        """Return whether this player won its most recent battle."""
        return self._battle_history[-1].win_probability == 1.0

    @property
    def turn_number(self) -> int:
        """Return the current turn number."""
        return self._turn_number

    @property
    def hero_health(self) -> int:
        """Return the current health of the hero."""
        return self._hero_health

    @property
    def tavern_tier(self) -> int:
        """Return the current tier of the tavern."""
        return self._tavern_tier

    @property
    def gold(self) -> int:
        """Return the current gold that the player has."""
        return self._gold

    @property
    def is_frozen(self) -> bool:
        """Return whether the recruit selection is currently frozen."""
        return self._is_frozen

    @property
    def refresh_cost(self) -> int:
        """Return the current cost of refreshing the recruitment pool."""
        return self._refresh_cost

    @property
    def hand(self) -> List[Minion]:
        """Return a list of the minions in the player's hand.
        Elements that are None mean that there is no minion in the hand at that index.
        """
        return self._hand

    @property
    def board(self) -> List[Minion]:
        """Return a list of the minions on the board.
        Elements that are None mean that there is no minion on the board at that index.
        """
        return self._board

    @property
    def recruits(self) -> List[Minion]:
        """Return a list of the minions available for purchase.
        Elements that are None mean that there is no recruit at that index.
        """
        return self._recruits

    @property
    def pool(self) -> MinionPool:
        """Return the pool of minions to select recruits from."""
        return self._pool


class TurnClock:
    """Tracks the passage of time in terms of turns.

    Instance Attributes:
        duration: The number of turns until the clock is complete.

    >>> clock = TurnClock(2)
    >>> clock.step()  # Turn 1
    False
    >>> clock.step()  # Turn 2
    True
    """
    # Private Instance Attributes:
    #   - _remaining: The number of turns remaining.
    #   - _on_complete: A function called when the clock is complete.

    def __init__(self, duration: int, on_complete: Optional[callable] = None) -> None:
        """Initialise the TurnClock with a duration.

        Args:
            duration: The number of turns until the clock is complete.
            on_complete: A function to call when the clock is complete.
                         This is called on the turn that the clock is complete.
        """
        self.duration = duration
        self._on_complete = on_complete
        self.reset()

    def step(self, n: int = 1) -> bool:
        """Step the clock by the given number of turns. Return whether the clock is complete."""
        if self.done:
            return True

        self._remaining -= n
        done = self.done
        if done and self._on_complete is not None:
            self._on_complete()

        return done

    def reset(self) -> None:
        """Reset the clock."""
        self._remaining = self.duration

    @property
    def done(self) -> bool:
        """Return whether the clock is complete."""
        return self._remaining <= 0


class BattlegroundsGame:
    """A class representing the state of a Hearthstone Battlegrounds game."""
    # Private Instance Attributes
    #   - _num_players: The number of players at the start of the game.
    #   - _boards: The recruitment game board for each player.
    #   - _pool: The pool of minions shared across all players.
    #   - _active_player: The player currently completing their turn.
    #   - _turn_completion: A list containing whether each player has completed their turn for this
    #                       round. The i-th element gives the turn completion for player i.
    #   - _round_number: The current round (where 1 indicates the first round).
    _num_players: int
    _boards: List[TavernGameBoard]
    _pool: MinionPool
    _active_player: Optional[int] = None
    _turn_completion: List[bool]
    _round_number: int

    def __init__(self, num_players: int = 8) -> None:
        """Initialise the BattlegroundsGame with the given number of players.
        Raise ValueError if num_players is negative or odd.

        Args:
            num_players: The number of players at the start of the game.
                         This MUST be an even positive integer.

        Preconditions:
            - num_players > 0
            - num_players % 2 == 0
        """
        self._num_players = num_players
        # Initialise an empty tavern for each player.
        self._pool = MinionPool()
        self._boards = [TavernGameBoard(pool=self._pool) for _ in range(num_players)]
        # Turn state
        self._active_player = None
        self._turn_completion = [False] * num_players
        self._round_number = 1

    @contextmanager
    def turn_for_player(self, player: int) -> TavernGameBoard:
        """A context manager that automatically starts and ends a turn for the given player.
        Return the TavernGameBoard of the player.

        Raise a ValueError if the turn could not be started.

        Preconditions:
            - 0 <= player < self.num_players
        """
        try:
            self.start_turn_for_player(player)
            yield self.active_board
        finally:
            self.end_turn()

    def start_turn_for_player(self, player: int) -> None:
        """Start the turn for the given player.
        Raise a ValueError if the turn could not be started.

        Preconditions:
            - 0 <= player < self.num_players
        """
        if self.is_turn_in_progress:
            raise ValueError('A turn is currently in progress!')
        if self.has_completed_turn(player):
            raise ValueError(f'Player {player} has already completed their turn for this round.')

        self._active_player = player
        self.active_board.next_turn()

    def end_turn(self) -> None:
        """End the turn for the currently active player.
        Raise a ValueError if no player's turn is active.
        """
        if not self.is_turn_in_progress:
            raise ValueError('No player is currently in a turn!')
        self._turn_completion[self._active_player] = True
        self._active_player = None

    def next_round(self) -> None:
        """Matchups pairs of players and starts the combat phase. Resets the game to the next
        round. Do nothing if the game is done.

        Raise a ValueError if a player has not yet completed their turn.
        """
        if any(not self.has_completed_turn(i) for i in range(self._num_players)):
            raise ValueError('A player has not completed their turn!')

        if self.is_done:
            return

        # Get the boards that are still alive
        alive_boards = self.alive_boards
        random.shuffle(alive_boards)
        # Partition boards into pairs
        for i in range(0, self._num_players, 2):
            board_a, board_b = alive_boards[i:i + 2]
            board_a.battle(board_b)

        # Reset turn completion
        self._turn_completion = [False] * self._num_players
        self._round_number += 1

    @property
    def is_done(self) -> bool:
        """Return whether the game is done.
        The game is done when there is a single player remaining.
        """
        return len(self.alive_boards) == 1

    @property
    def boards(self) -> List[TavernGameBoard]:
        """Return a list of all the game boards."""
        return self._boards

    @property
    def alive_boards(self) -> List[TavernGameBoard]:
        """Return a list of all the game boards that are still alive."""
        return [board for board in self._boards if not board.is_dead]

    @property
    def active_board(self) -> Optional[TavernGameBoard]:
        """Return the game board of the player currently completing their turn,
        or None if no player is completing their turn.
        """
        return None if self._active_player is None else self._boards[self._active_player]

    @property
    def is_turn_in_progress(self) -> bool:
        """Return whether a turn is currently in progress."""
        return self._active_player is not None

    def has_completed_turn(self, player: int) -> bool:
        """Return whether the given player has completed their turn.

        Preconditions:
            - 0 <= player < self.num_players
        """
        return self._turn_completion[player]

    @property
    def round_number(self) -> int:
        """Return the current round."""
        return self._round_number


class Move:
    """A class representing a move in Hearthstone Battlegrounds.

    Instance Attributes:
        - action: The type of this move.
        - index: An optional index for specifying a minion to apply the action on.
    """
    action: Action
    index: Optional[int] = None

    def __init__(self, action: Action, index: Optional[int] = None) -> None:
        """Initialise the Move.

        Preconditions:
            - index is not None or action in {Action.UPGRADE, Action.REFRESH, Action.FREEZE, Action.END_TURN}
            - index is None or action in {Action.BUY_MINION, Action.SELL_MINION, Action.PLAY_MINION}
            - action != Action.BUY_MINION or 0 <= index < MAX_TAVERN_RECRUIT_SIZE
            - action != Action.SELL_MINION or 0 <= index < MAX_TAVERN_BOARD_SIZE
            - action != Action.PLAY_MINION or 0 <= index < MAX_HAND_SIZE
        """
        self.action = action
        self.index = index

    @property
    def move_id(self) -> int:
        """Return the unique integer id of this move."""
        return int(self.action) + (self.index or 0)

    @staticmethod
    def from_id(move_id: int) -> Move:
        """Return the Move represented by the given id.

        Preconditions:
            - Action.UPGRADE <= move_id <= Action.END_TURN
        """
        if move_id == Action.UPGRADE:
            return Move(Action.UPGRADE)
        elif move_id == Action.REFRESH:
            return Move(Action.REFRESH)
        elif move_id == Action.FREEZE:
            return Move(Action.FREEZE)
        elif Action.BUY_MINION <= move_id < Action.SELL_MINION:
            return Move(Action.BUY_MINION, move_id - Action.BUY_MINION)
        elif Action.SELL_MINION <= move_id < Action.PLAY_MINION:
            return Move(Action.SELL_MINION, move_id - Action.SELL_MINION)
        elif Action.PLAY_MINION <= move_id < Action.END_TURN:
            return Move(Action.PLAY_MINION, move_id - Action.PLAY_MINION)
        elif move_id == Action.END_TURN:
            return Move(Action.END_TURN)
        else:
            raise ValueError(f'{move_id} is not a valid move id!')

    def __str__(self) -> str:
        return f'Move(action={self.action}, index={self.index})'

    def __repr__(self) -> str:
        return f'Move(action={repr(self.action)}, index={repr(self.index)})'


class Action(IntEnum):
    """A class representing the different types of actions in Hearthstone Battlegrounds.

    Instance Attributes:
        - UPGRADE: Upgrades the tavern.
        - REFRESH: Refresh the minions available for purchase.
        - FREEZE: Freeze the minions available for purchase.
        - BUY: Buy a minion from the tavern. This value corresponds to the action of buying
               the minion at index 0 of the available pool. The action for buying the minion at
               index i from the pool is simply offset (by i) from this action.
        - SELL: Sell a minion from the tavern. This value corresponds to the action of selling
                the minion at index 0 on the board. The action for buying the minion at index i
                on the board is simply offset (by i) from this action.
        - PLAY: Play a minion from the hand. This value corresponds to the action of playing
                the minion at index 0 in the hand. The action for playing the minion at index i
                in the hand is simply offset (by i) from this action.
        - END_TURN: End the current turn.
    """
    UPGRADE = 0
    REFRESH = 1
    FREEZE = 2
    BUY_MINION = 3
    SELL_MINION = BUY_MINION + MAX_TAVERN_RECRUIT_SIZE
    PLAY_MINION = SELL_MINION + MAX_TAVERN_BOARD_SIZE
    END_TURN = PLAY_MINION + MAX_HAND_SIZE


if __name__ == '__main__':
    import doctest
    doctest.testmod()
