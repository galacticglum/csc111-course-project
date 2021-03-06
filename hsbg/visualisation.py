"""A module containing visualisation related functionality.

This file is Copyright (c) 2021 Shon Verch and Grace Lin.
"""
from typing import Tuple, Optional

import pygame

from hsbg.models import Minion, MECHANIC_ABILITIES
from hsbg import TavernGameBoard, BattlegroundsGame


# Colours
GOLDEN_COLOUR = (218, 165, 32)
BLACK_COLOUR = (0, 0, 0)
RED_COLOUR = (255, 0, 0)
FROZEN_COLOUR = (52, 204, 235)

# Sizing and location
BORDER_PADDING = 20
BORDER_WIDTH = 2

# The padding, in pixels, for the top labels.
TOP_LABEL_PADDING = 15
# The font size of top labels.
TOP_LABEL_FONT_SIZE = 72

# Default screen dimesnions
TARGET_SCREEN_WIDTH = 1600
TARGET_SCREEN_HEIGHT = 900


def visualise_game_board(board: TavernGameBoard, width: int = TARGET_SCREEN_WIDTH,
                         height: int = TARGET_SCREEN_HEIGHT) -> None:
    """Visualise the current state of a game board.

    Args:
        board: The board to visualise.
        width: The width of the screen
        height: The height of the screen.
    """
    screen = init_display(width, height)
    running = True
    while running:
        # Search for a quit event
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                running = False

        draw_game_board(screen, board)
        flip_display()

    close_display()


def init_display(width: int = TARGET_SCREEN_WIDTH, height: int = TARGET_SCREEN_HEIGHT) \
        -> pygame.Surface:
    """Initialise a pygame display with the given dimensions."""
    pygame.init()
    return pygame.display.set_mode([width, height])


def flip_display() -> None:
    """Flip the display."""
    # Flip screen buffers
    pygame.display.flip()


def close_display() -> None:
    """Close the display."""
    pygame.quit()


def draw_game(surface: pygame.Surface, game: BattlegroundsGame, delay: Optional[int] = None) \
        -> None:
    """Visualise the board of the active player in the game.
    Raise a ValueError if there is no active player.
    """
    if not game.is_turn_in_progress:
        raise ValueError('No player is currently in a turn!')

    pygame.display.set_caption(
        f'Hearthstone Battlegrounds Simulator - Player {game.active_player + 1}')
    draw_game_board(surface, game.active_board)

    previous_move = None

    font = get_font(surface, 24)
    # Draw active player
    active_player_text = f'Player: {game.active_player + 1}'
    text_width, text_height = font.size(active_player_text)
    position = (surface.get_width() - text_width - TOP_LABEL_PADDING, TOP_LABEL_PADDING)
    draw_text_for_board(surface, active_player_text, position, 24)
    # Draw previous move
    previous_move = game.previous_move[1] if game.previous_move is not None else None
    previous_move_text = f'Previous move: {previous_move}'
    text_width, _ = font.size(previous_move_text)
    position = (surface.get_width() - text_width - TOP_LABEL_PADDING, text_height +
                TOP_LABEL_PADDING)
    draw_text_for_board(surface, previous_move_text, position, 24)

    if delay is not None:
        pygame.time.wait(delay)


def draw_game_board(surface: pygame.Surface, board: TavernGameBoard) -> None:
    """Visualise the current state of a game board on the given surface.
    Note that this clears the current contents of the surface.

    Args:
        surface: The surface to draw on.
        board: The board to visualise.
        delay: The number of milliseconds to wait after drawing the board.
    """
    # Fill the background
    surface.fill((255, 255, 255))

    screen_width, screen_height = surface.get_size()
    draw_top_labels(surface, [
        (f'Gold: {board.gold},', GOLDEN_COLOUR),
        (f'Tier: {board.tavern_tier},', BLACK_COLOUR),
        (f'Hero Health: {board.hero_health}', RED_COLOUR)
    ])

    minions_containers = [board.recruits, board.board, board.hand]
    for index, minions in enumerate(minions_containers):
        start_y, end_y = draw_minion_container(surface, index)
        cell_width = screen_width // len(minions)
        for i in range(len(minions)):
            x = cell_width * i
            pygame.draw.line(surface, BLACK_COLOUR, (x, start_y), (x, end_y))
            rect = (x + 10, start_y + 10, cell_width - 20, end_y - start_y - 10)
            draw_minion(surface, minions[i], rect)

            if board.is_frozen and index == 0:
                s = pygame.Surface((cell_width, end_y - start_y))
                s.set_alpha(127)
                s.fill(FROZEN_COLOUR)
                surface.blit(s, (x, start_y))


def draw_top_labels(surface: pygame.Surface, labels: list) -> None:
    """Draw list of labels."""
    current_label_x = _scale_x(surface, TOP_LABEL_PADDING)
    current_label_y = _scale_y(surface, TOP_LABEL_PADDING)
    for label in labels:
        position = (current_label_x, current_label_y)
        width, _ = draw_text_for_board(surface, label[0], position,
                                       TOP_LABEL_FONT_SIZE, label[1])
        current_label_x += width + _scale_x(surface, TOP_LABEL_PADDING) * 2


def draw_minion_container(surface: pygame.Surface, index: int) -> Tuple[int, int]:
    """Draw the containing rectangle for the minions on the board.
    Return the top and bottom coordinates as a tuple.
    """
    start_y = _scale_y(surface, TOP_LABEL_PADDING * 2 + TOP_LABEL_FONT_SIZE)
    height = (surface.get_height() - start_y) // 3

    padding = 1 if index == 1 else 0
    start_y += height * index + padding / 2
    pygame.draw.rect(surface, BLACK_COLOUR, (-10, start_y, surface.get_width() + 10000, height), 1)
    return (start_y, start_y + height)


def get_font(surface: pygame.Surface, font_size: int) -> pygame.font.Font:
    """Return the pygame Font object for the given size."""
    font_size = min(font_size * surface.get_height() // TARGET_SCREEN_HEIGHT,
                    font_size * surface.get_width() // TARGET_SCREEN_WIDTH)
    font = pygame.font.SysFont('inconsolata', font_size)
    return font


def draw_text_for_board(surface: pygame.Surface, text: str, pos: tuple[int, int],
                        font_size: int, color: tuple = (0, 0, 0)) -> Tuple[int, int]:
    """Draw the given text to the pygame screen at the given position.
    Return the size of the drawn text surface.

    pos represents the *upper-left corner* of the text.
    """
    font = get_font(surface, font_size)
    text_surface = font.render(text, True, color)
    width, height = text_surface.get_size()
    surface.blit(text_surface, pygame.Rect(pos, (pos[0] + width, pos[1] + height)))
    return (width, height)


def draw_text_word_wrap(surface: pygame.Surface, text: str, rect: tuple, font_size: int,
                        colour: tuple = (0, 0, 0), aa: bool = True, line_spacing: int = 2,
                        alpha: int = 255) -> Tuple[str, int]:
    """Draw text in the given rect, automatically wraping words.
    Return any text that wasn't drawn, and the final y coordinate.
    """
    rect = pygame.Rect(rect)
    y = rect.top

    # get the height of the font
    font = get_font(surface, font_size)
    font_height = font.get_height()

    while text:
        i = 1
        # determine if the row of text will be outside our area
        if y + font_height > rect.bottom:
            break
        # determine maximum width of line
        while font.size(text[:i])[0] < rect.width and i < len(text):
            i += 1

        # if we've wrapped the text, then adjust the wrap to the last word
        if i < len(text):
            i = text.rfind(" ", 0, i) + 1

        # render the line and blit it to the surface
        image = font.render(text[:i], aa, colour)
        image.set_alpha(alpha)

        surface.blit(image, (rect.left, y))
        y += font_height + line_spacing

        # remove the text we just blitted
        text = text[i:]

    return text, y


def draw_minion(surface: pygame.Surface, minion: Optional[Minion], rect: tuple) -> None:
    """Draw a minion on the screen at the given position with the given size.

    Args:
        surface: The surface to draw on.
        minion: The minion to draw.
        rect: The area to draw the minion in.
    """
    if minion is None:
        draw_text_word_wrap(surface, '(empty)', rect, 26, alpha=127)
        return

    # Draw minion name
    minion_name_text = f'{minion.name} ({minion.tier})'
    colour = GOLDEN_COLOUR if minion.is_golden else BLACK_COLOUR
    _, minion_name_end_y = draw_text_word_wrap(surface, minion_name_text, rect, 26, colour)

    # Draw attack/health stats
    attack_health_text = f'{minion.current_attack} ATK / {minion.current_health} HP'
    attack_health_position = (rect[0], minion_name_end_y + 10)
    draw_text_for_board(surface, attack_health_text, attack_health_position, 20)

    # Draw abilities
    abilities_to_draw = [a.name[0] for a in MECHANIC_ABILITIES if a in minion.current_abilities]
    ability_text = str(','.join(abilities_to_draw))

    font = get_font(surface, 26)
    _, text_height = font.size(ability_text)

    draw_text_for_board(surface, ability_text, (rect[0], rect[1] + rect[3] - text_height - 10), 26)


def _scale_x(surface: pygame.Surface, x: float) -> float:
    """Return the given horizontal coordinate scaled proportionally with the target resolution."""
    return x * (surface.get_width() / TARGET_SCREEN_WIDTH)


def _scale_y(surface: pygame.Surface, y: float) -> float:
    """Return the given vertical coordinate scaled proportionally with the target resolution."""
    return y * (surface.get_height() / TARGET_SCREEN_HEIGHT)


def _scale(surface: pygame.Surface, position: Tuple[float, float]) -> Tuple[float, float]:
    """Return the given coordinate scaled proportionally with the target resolution."""
    x, y = position
    return (_scale_x(surface, x), _scale_y(surface, y))


if __name__ == '__main__':
    import doctest
    doctest.testmod()

