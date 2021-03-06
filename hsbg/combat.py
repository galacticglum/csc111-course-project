"""A simulator of the combat phase in Hearthstone Battlegrounds.
This file is Copyright (c) 2021 Shon Verch and Grace Lin.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from typing import List

from hsbg_sim import (
    run_simulator,
    Board as SimulatorBoard,
    Minion as SimulatorMinion,
    BattleResult as SimulatorBattleResult
)

from hsbg.models import CardAbility


@dataclass
class Battle:
    """The result of the combat phase simulator.

    Instance Attributes:
        - win_probability: The probability of winning this battle.
        - tie_probability: The probability of a tie.
        - lose_probability: The probability of losing this battle.
        - mean_score: The mean score across all simulations of the battle.
        - median_score: The median score across all simulations of the battle.
        - mean_damage_taken: The mean damage taken (by the friendly hero)
            across all simulations of the battle.
        - mean_damage_dealt: The mean damage dealt (to the enemy hero)
            across all simulations of the battle.
        - expected_hero_health: The expected health of the hero after this battle.
        - expected_enemy_hero_health: The expected health of the enemy hero after this battle.
        - death_probability: The probability of the hero dying after this battle.
        - enemy_death_probability: The probability of the enemy hero dying after this battle.

    Representation Invariants:
        - 0 <= self.win_probability <= 1
        - 0 <= self.tie_probability <= 1
        - 0 <= self.lose_probability <= 1
        - self.win_probability + self.tie_probability + self.lose_probability == 1
        - 0 <= self.death_probability <= 1
        - 0 <= self.enemy_death_probability <= 1
    """
    win_probability: float
    tie_probability: float
    lose_probability: float
    mean_score: float
    median_score: float
    mean_damage_taken: float
    mean_damage_dealt: float
    expected_hero_health: float
    expected_enemy_hero_health: float
    death_probability: float
    enemy_death_probability: float

    def invert(self) -> Battle:
        """Return a new Battle where the friendly and enemy players are swapped."""
        return Battle(self.lose_probability, self.tie_probability, self.win_probability,
                      -self.mean_score, -self.median_score,
                      self.mean_damage_dealt, self.mean_damage_taken,
                      self.expected_enemy_hero_health, self.expected_hero_health,
                      self.enemy_death_probability, self.death_probability)

    @staticmethod
    def from_battle_result(battle_result: SimulatorBattleResult) -> Battle:
        """Return the Battle representing the given BattleResult object."""
        # A simple wrapper over the SimulatorBattleResult object from the hsbg_sim module.
        return Battle(
            battle_result.win_probability,
            battle_result.tie_probability,
            battle_result.lose_probability,
            battle_result.mean_score,
            battle_result.median_score,
            battle_result.mean_damage_taken,
            battle_result.mean_damage_dealt,
            battle_result.expected_hero_health,
            battle_result.expected_enemy_hero_health,
            battle_result.death_probability,
            battle_result.enemy_death_probability
        )

    @staticmethod
    def parse_simulator_output(output: str) -> Battle:
        """Return the Battle representing a string-based representation of the battle result.
        The output argument should match the output format of the C++ simulator.

        >>> outputs = '''
        ... --------------------------------
        ... win: 76.9%, tie: 0.0%, lose: 23.1%
        ... mean score: 11.875, median score: -16
        ... percentiles: -12 -10 -3 16 16 16 16 20 20 20 20
        ... mean damage taken: 1.764
        ... your expected health afterwards: 29.236, 3.14% chance to die
        ... mean damage dealt: 14.408
        ... their expected health afterwards: 10.592, 5.2% chance to die
        ... --------------------------------'''
        >>> expected = Battle(0.769, 0, 0.231, 11.875, -16, 1.764, 14.408,\
                              29.236, 10.592, 0.0314, 0.052)
        >>> expected == Battle.parse_simulator_output(outputs)
        True
        """
        def _get_field(name: str, value_suffix: str = '') -> float:
            """Return the value of a field in the simulator output string.
            Raise a ValueError if it could not be found.

            Note: A field is substring of the form: "<name>: <float>"

            Args:
                name: The name of the field.
                value_suffix: A suffix after the numerical value (e.g. '%' or '$')
                              to include while matching.
            """
            # Matches for "<name>: <float><value_suffix>"
            pattern = r'(?<={}:\s)-?\d+.?\d*{}'.format(name, value_suffix)
            match = re.search(pattern, output)
            if match is None:
                raise ValueError(f'Could not parse field with name \'{name}\' in:\n{output}')
            return float(match.group(0).replace(value_suffix, '').strip())

        def _get_death_probability(kind: str) -> float:
            """Return the probability of death for the given hero.
            Raise a ValueError if it could not be found.

            Preconditions:
                - kind in {'friendly', 'enemy'}
            """
            if kind == 'friendly':
                pattern = r'(?<=your expected health afterwards: ).*(?=% chance to die)'
            else:
                pattern = r'(?<=their expected health afterwards: ).*(?=% chance to die)'

            match = re.search(pattern, output)
            if match is None:
                raise ValueError(f'Could not find death probability for {kind} hero in:\n{output}.')

            parts = match.group(0).split(',')
            probability = parts[1].strip()
            probability = round(float(probability) / 100, len(probability) + 1)
            return probability

        # Get win, tie, and lose probabilities
        win_probability = _get_field('win', value_suffix='%') / 100
        tie_probability = _get_field('tie', value_suffix='%') / 100
        lose_probability = _get_field('lose', value_suffix='%') / 100

        # Get score stats
        mean_score = _get_field('mean score')
        median_score = _get_field('median score')

        # Get damage stats
        mean_damage_taken = _get_field('mean damage taken')
        mean_damage_dealt = _get_field('mean damage dealt')
        expected_hero_health = _get_field('your expected health afterwards')
        expected_enemy_hero_health = _get_field('their expected health afterwards')

        # Get death probabilities
        death_probability = _get_death_probability('friendly')
        enemy_death_probability = _get_death_probability('enemy')

        return Battle(win_probability, tie_probability, lose_probability,
                      mean_score, median_score, mean_damage_taken, mean_damage_dealt,
                      expected_hero_health, expected_enemy_hero_health,
                      death_probability, enemy_death_probability)


def simulate_combat(friendly_board: TavernGameBoard, enemy_board: TavernGameBoard, n: int = 1000) \
        -> Battle:
    """Simulate a battle between the given friendly and enemy boards.
    Return a Battle object containing match statistics averaged over all the runs.

    Args:
        friendly_board: The state of the friendly player's board.
        enemy_board: The state of the enemy player's board.
        n: The number of times to simulate the battle.
    """
    battle_result = run_simulator(
        to_simulator_board(friendly_board),  # The friendly board
        to_simulator_board(enemy_board),  # The enemy board
        n  # Number of times to simulate
    )
    return Battle.from_battle_result(battle_result)


def to_simulator_board(board: TavernGameBoard) -> SimulatorBoard:
    """Return the given TavernGameBoard as a SimulatorBoard."""
    minions = []
    for minion in board.get_minions_on_board():
        minions.append(SimulatorMinion(
            name=minion.name,
            attack=minion.current_attack,
            health=minion.current_health,
            is_golden=minion.is_golden,
            taunt=CardAbility.TAUNT in minion.current_abilities,
            divine_shield=CardAbility.DIVINE_SHIELD in minion.current_abilities,
            poisonous=CardAbility.POISONOUS in minion.current_abilities,
            windfury=CardAbility.WINDFURY in minion.current_abilities,
            reborn=CardAbility.REBORN in minion.current_abilities
        ))
    return SimulatorBoard(
        tavern_tier=board.tavern_tier,
        hero_health=board.hero_health,
        minions=minions
    )


def battle_to_commands(friendly_board: TavernGameBoard, enemy_board: TavernGameBoard) -> List[str]:
    """Return the series of simulator commands that define the given battle."""
    return (
        ['Board'] + game_board_to_commands(friendly_board)
        + ['VS'] + game_board_to_commands(enemy_board)
    )


def game_board_to_commands(board: TavernGameBoard) -> List[str]:
    """Return the series of simulator commands that define the given board."""
    lines = [
        f'level {board.tavern_tier}',
        f'health {board.hero_health}',
    ]

    for minion in board.board:
        if minion is None:
            continue
        lines.append(f'* {minion}')

    return lines


def game_board_to_str(board: TavernGameBoard) -> str:
    """Return the string representation of this TavernGameBoard.

    >>> from hsbg import TavernGameBoard
    >>> board = TavernGameBoard()
    >>> minions = [board.pool.find(name='Alleycat', is_golden=True),
    ...            board.pool.find(name='Murloc Scout'),
    ...            board.pool.find(name='Rockpool Hunter')]
    >>> all(board.add_minion_to_hand(minion) for minion in minions)
    True
    >>> all(board.play_minion(i) for i in range(len(minions)))
    True
    >>> print(game_board_to_str(board))
    level 1
    health 40
    * 2/2 golden Alleycat
    * 2/2 golden Tabbycat
    * 2/2 Murloc Scout
    * 2/3 Rockpool Hunter
    >>> coldlight_seer = board.pool.find(name='Coldlight Seer', is_golden=True)
    >>> board.add_minion_to_hand(coldlight_seer) and board.play_minion(0)
    True
    >>> print(game_board_to_str(board))
    level 1
    health 40
    * 2/2 golden Alleycat
    * 2/2 golden Tabbycat
    * 2/6 Murloc Scout
    * 2/7 Rockpool Hunter
    * 4/6 golden Coldlight Seer
    >>> from models import Buff, CardAbility
    >>> board.board[4].add_buff(Buff(1, 0, CardAbility.TAUNT | CardAbility.DIVINE_SHIELD))
    >>> board.give_gold(10)
    >>> board.upgrade_tavern()
    True
    >>> print(game_board_to_str(board))
    level 2
    health 40
    * 2/2 golden Alleycat
    * 2/2 golden Tabbycat
    * 2/6 Murloc Scout
    * 2/7 Rockpool Hunter
    * 5/6 golden Coldlight Seer, taunt, divine shield
    """
    return '\n'.join(game_board_to_commands(board))


if __name__ == '__main__':
    # The problems underlined in red are PyCharm
    # just not realizing copy was used, the code works!
    import doctest
    doctest.testmod()
