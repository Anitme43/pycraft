import cProfile, pdb, os

from time import time, sleep
from math import radians
from random import random

import console as c
from colours import init_colours
from console import DEBUG, log, in_game_log, CLS, SHOW_CUR, HIDE_CUR
from nbinput import NonBlockingInput

import saves, ui, terrain, player, render, server_interface, data


def setup_render_c(settings):
    global render_c

    import sys, glob
    if len(glob.glob('build/lib.*')): sys.path.append(glob.glob('build/lib.*')[0])

    try: import render_c
    except ImportError: settings['render_c'] = False


def main():
    settings = None
    try:
        meta, settings, profile, debug, name, port = setup()

        setup_render_c(settings)

        while True:
            data = ui.main(meta, settings)

            if data is None:
                break

            if data['local']:
                # Local Server
                server_obj = server_interface.LocalInterface(name, data['save'], port)
            else:
                # Remote Server
                server_obj = server_interface.RemoteInterface(name, data['ip'], data['port'])

            if not server_obj.error:
                if profile:
                    cProfile.runctx('game(server_obj, settings)', globals(), locals(), filename='game.profile')
                elif debug:
                    pdb.run('game(server_obj, settings)', globals(), locals())
                else:
                    game(server_obj, settings)

            if server_obj.error:
                ui.error(server_obj.error)

    finally:
        setdown()


def setup():
    log('Start\n')
    print(CLS)

    meta = saves.get_global_meta()
    settings = saves.get_settings()

    profile = c.getenv_b('PYCRAFT_PROFILE')

    # For internal PDB debugging
    debug = c.getenv_b('PYCRAFT_DEBUG')

    # For externally connecting GDB
    with open('.pid', 'w') as f:
        print(os.getpid(), file=f)

    name = c.getenv('PYCRAFT_NAME') or settings.get('name') or ui.name(settings)
    port = c.getenv('PYCRAFT_PORT') or meta.get('port') or 0

    init_colours(settings)
    saves.check_map_dir()

    print(HIDE_CUR + CLS)
    return meta, settings, profile, debug, name, port


def setdown():
    print(SHOW_CUR + CLS)


def game(server, settings):
    dt = 0  # Tick
    df = 0  # Frame
    dc = 0  # Cursor
    ds = 0  # Selector
    dpos = False
    dinv = False  # Inventory
    dcraft = False  # Crafting
    FPS = 15  # Max
    MPS = 15  # Movement

    old_bk_objects = None
    old_edges = None
    redraw_all = True
    last_frame = {}
    last_out = time()
    last_move = time()
    inp = None
    jump = 0
    cursor = 0
    crafting = False
    crafting_sel = 0
    crafting_list = []
    inv_sel = 0
    cursor_hidden = True
    new_blocks = {}
    alive = True
    events = []

    crafting_list, crafting_sel = player.get_crafting(
        server.inv,
        crafting_list,
        crafting_sel
    )

    # Game loop
    with NonBlockingInput() as nbi:
        while server.game:
            x, y = server.pos
            dt = server.dt()
            frame_start = time()

            ## Input

            char = True
            inp = []
            while char:
                # Receive input if a key is pressed
                char = nbi.char()
                if char:
                    char = str(char).lower()

                    if char in 'wasdkjliuoc-=\n ':
                        inp.append(char)

            # Hard pause
            if DEBUG and '\n' in inp:
                input()
                inp.remove('\n')

            # Pause game
            if ' ' in inp or '\n' in inp:
                server.redraw = True
                redraw_all = True
                if ui.pause(server, settings) == 'exit':
                    server.logout()
                    continue

            # Update player position
            move_period = 1 / MPS
            while frame_start >= move_period + last_move:

                dx, dy, jump = player.get_pos_delta(
                    inp, server.map_, x, y, jump, settings.get('flight'))
                if dx or dy:
                    dpos = True
                    x += dx
                    y += dy

                if x in server.map_ and not settings.get('flight'):
                    # Player falls when no solid block below it and not jumping
                    jump -= dt
                    if jump <= 0:
                        jump = 0
                        if not terrain.is_solid(server.map_[x][y + 1]):
                            # Fall
                            y += 1
                            dpos = True

                last_move += move_period

            ## Update Map

            width = settings.get('width')
            height = settings.get('height')

            # Finds display boundaries
            edges = (x - int(width / 2), x + int(width / 2))
            edges_y = (y - int(height / 2), y + int(height / 2))

            if edges_y[1] > data.world_gen['height']:
                edges_y = (data.world_gen['height'] - height, data.world_gen['height'])
            elif edges_y[0] < 0:
                edges_y = (0, height)

            extended_edges = (edges[0]-render.max_light, edges[1]+render.max_light)

            slice_list = terrain.detect_edges(server.map_, extended_edges)
            if slice_list:
                log('slices to load', slice_list)
                chunk_list = terrain.get_chunk_list(slice_list)
                server.get_chunks(chunk_list)
                server.unload_slices(extended_edges)

            # Moving view
            if not edges == old_edges or server.view_change:
                extended_view = terrain.move_map(server.map_, extended_edges)
                old_edges = edges
                server.redraw = True
                server.view_change = False

            # Sun has moved
            bk_objects, sky_colour, day = render.bk_objects(server.time, width, settings.get('fancy_lights'))
            if not bk_objects == old_bk_objects:
                old_bk_objects = bk_objects
                server.redraw = True

            if settings.get('gravity'):
                blocks = terrain.apply_gravity(server.map_, edges)
                if blocks: server.set_blocks(blocks)

            ## Crafting

            if 'c' in inp:
                server.redraw = True
                crafting = not crafting and len(crafting_list)

            dcraft, dcraftC, dcraftN = False, False, False
            if dinv: crafting = False
            if crafting:
                # Craft if player pressed craft
                server.inv, inv_sel, crafting_list, dcraftC = \
                    player.crafting(inp, server.inv, inv_sel,
                        crafting_list, crafting_sel)

                # Increment/decrement craft no.
                crafting_list, dcraftN = \
                    player.craft_num(inp, server.inv, crafting_list,
                        crafting_sel)

                dcraft = dcraftC or dcraftN

            # Update crafting list
            if dinv or dcraft:
                crafting_list, crafting_sel = \
                    player.get_crafting(server.inv, crafting_list,
                                        crafting_sel, dcraftC)
                if not len(crafting_list): crafting = False

            dc = player.move_cursor(inp)
            cursor = (cursor + dc) % 6

            ds = player.move_sel(inp)
            if crafting:
                crafting_sel = ((crafting_sel + ds) % len(crafting_list)
                                   if len(crafting_list) else 0)
            else:
                inv_sel = ((inv_sel + ds) % len(server.inv)
                              if len(server.inv) else 0)

            if any((dpos, dc, ds, dinv, dcraft)):
                server.redraw = True
            if dpos:
                dpos = False
                server.pos = x, y
                cursor_hidden = True
            if dc:
                cursor_hidden = False

            new_blocks, server.inv, inv_sel, new_events, dinv = \
                player.cursor_func(
                    inp, server.map_, x, y, cursor, inv_sel, server.inv
                )

            if new_blocks:
                server.set_blocks(new_blocks)

            events += new_events

            new_blocks = {}
            for i in range(int(dt)):
                new_blocks.update(process_events(events, server.map_))
            if new_blocks:
                server.set_blocks(new_blocks)

            # If no block below, kill player
            try:
                block = server.map_[x][y+1]
            except IndexError:
                alive = False

            # Respawn player if dead
            if not alive:
                alive = True
                server.respawn()

            ## Render

            if server.redraw:
                server.redraw = False

                objects = player.assemble_players(
                    server.current_players, x, y, int(width / 2), edges
                )

                if not cursor_hidden:
                    cursor_colour = player.cursor_colour(
                        x, y, cursor, server.map_, server.inv, inv_sel
                    )

                    objects.append(player.assemble_cursor(
                        int(width / 2), y, cursor, cursor_colour
                    ))

                lights = render.get_lights(extended_view, edges[0], bk_objects)

                render_map = render_c.render_map if settings.get('render_c') else render.render_map

                out, last_frame = render_map(
                    server.map_,
                    server.slice_heights,
                    edges,
                    edges_y,
                    objects,
                    bk_objects,
                    sky_colour,
                    day,
                    lights,
                    settings,
                    last_frame,
                    redraw_all
                )

                redraw_all = False

                crafting_grid = render.render_grid(
                    player.CRAFT_TITLE, crafting, crafting_list,
                    height, crafting_sel
                )

                inv_grid = render.render_grid(
                    player.INV_TITLE, not crafting, server.inv,
                    height, inv_sel
                )

                label = (player.label(crafting_list, crafting_sel)
                        if crafting else
                        player.label(server.inv, inv_sel))

                out += render.render_grids(
                    [
                        [inv_grid, crafting_grid],
                        [[label]]
                    ],
                    width, height
                )

                print(out)
                in_game_log('({}, {})'.format(x, y), 0, 0)

            d_frame = time() - frame_start
            if d_frame < (1/FPS):
                sleep((1/FPS) - d_frame)


def process_events(events, map_):
    new_blocks = {}

    for event in events:
        if event['time_remaining'] <= 0:
            ex, ey = event['pos']

            # Boom
            radius = 5
            blast_strength = 85
            for tx in range(ex - radius*2, ex + radius*2):
                new_blocks[tx] = {}

                for ty in range(ey - radius, ey + radius):

                    if (render.in_circle(tx, ty, ex, ey, radius) and tx in map_ and ty >= 0 and ty < len(map_[tx]) and
                            player.can_strength_break(map_[tx][ty], blast_strength)):

                        if not render.in_circle(tx, ty, ex, ey, radius - 1):
                            if random() < .5:
                                new_blocks[tx][ty] = ' '
                        else:
                            new_blocks[tx][ty] = ' '

            events.remove(event)
        else:
            event['time_remaining'] -= 1

    return new_blocks


if __name__ == '__main__':
    main()
