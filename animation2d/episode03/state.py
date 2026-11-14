"""Deterministic Episode 03 continuity ledger; counts are pancake units, not pieces.

Portions remaining are the plan for the single recipe before batter exists.
Serving counts retain allocated pancake units during bites, until the explicit
meal-completion ellipsis at shot 079. No raw tasting or added food is modeled.
"""
from copy import deepcopy

CAST = ('DAN', 'MAYA', 'NINA', 'LEO', 'ELLA', 'MAX')
DRY = {'flour_cups': 2, 'sugar_tbsp': 2, 'baking_powder_tbsp': 1, 'salt_tsp': .5}
WET = {'eggs': 2, 'milk_cups': 1.5, 'butter_tbsp': 3}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def initial_state():
    return dict(batch_count=1, vase_empty=True, vase_location='decoration_shelf', stove='OFF',
                hands_washed=False, dry={key: 0 for key in DRY}, wet={key: 0 for key in WET},
                butter_total_tbsp=4, butter_split=False, butter_melted=False, butter_cooled=False,
                wet_transferred=False, blue_bowl='empty', yellow_bowl='empty', rest='not_started',
                portions_remaining=12, pan={'count': 0, 'stage': 'empty'}, cooked_total=0,
                tray=0, served={name: 0 for name in CAST}, eaten_total=0,
                pairs_started=0, pairs_completed=0, pan_butter_sixths_remaining=6,
                plates_ready=0, table_ready=False, raw_tools_separate=True,
                meal_started=False, meal_finished=False, first_pancake_cut=False,
                dishware_cleared=False)


def validate_state(state):
    """Reject duplicate food, changed recipe, unsafe serving and impossible phases."""
    require(set(state) == set(initial_state()), 'state fields differ from continuity schema')
    require(state['batch_count'] == 1 and state['butter_total_tbsp'] == 4, 'one batch and four tablespoons butter are locked')
    require(state['vase_empty'] is True, 'vase must remain empty')
    require(state['vase_location'] in ('decoration_shelf', 'island'), 'unknown vase location')
    require(state['stove'] in ('OFF', 'ON'), 'invalid stove state')
    require(state['raw_tools_separate'] is True, 'raw and cooked tools must stay separate')
    for values, limits, label in ((state['dry'], DRY, 'dry'), (state['wet'], WET, 'wet')):
        require(set(values) == set(limits), f'{label}: ingredient keys changed')
        for key, value in values.items():
            require(isinstance(value, (int, float)) and 0 <= value <= limits[key], f'{key}: recipe allocation exceeded')
    for key, maximum in (('portions_remaining',12), ('cooked_total',12), ('tray',12), ('eaten_total',12),
                         ('pairs_started',6), ('pairs_completed',6), ('pan_butter_sixths_remaining',6), ('plates_ready',6)):
        require(type(state[key]) is int and 0 <= state[key] <= maximum, f'{key}: invalid count')
    require(set(state['served']) == set(CAST), 'serving ledger must contain exactly six family members')
    require(all(type(count) is int and 0 <= count <= 2 for count in state['served'].values()), 'each plate may receive only two pancakes')
    pan = state['pan']
    require(set(pan) == {'count','stage'} and pan['stage'] in ('empty','first_side','second_side','cooked'), 'invalid pan phase')
    require(pan['count'] == (0 if pan['stage'] == 'empty' else 2), 'pan must contain exactly one pair or be empty')
    require(state['portions_remaining'] == 12 - 2 * state['pairs_started'], 'batter portions do not match poured pairs')
    require(state['cooked_total'] == 2 * state['pairs_completed'], 'cooked count differs from completed pairs')
    pending = 1 if pan['stage'] in ('first_side','second_side') else 0
    require(state['pairs_started'] - state['pairs_completed'] == pending, 'cooking pair ledger is inconsistent')
    cooked_on_pan = pan['count'] if pan['stage'] == 'cooked' else 0
    require(state['tray'] + sum(state['served'].values()) + state['eaten_total'] + cooked_on_pan == state['cooked_total'], 'cooked pancake conservation failed')
    require(state['portions_remaining'] + pan['count'] + state['tray'] + sum(state['served'].values()) + state['eaten_total'] == 12, 'single-batch portion conservation failed')
    require(state['blue_bowl'] in ('empty','dry','batter','empty_after_cooking'), 'invalid blue bowl phase')
    require(state['yellow_bowl'] in ('empty','wet','film','emptied'), 'invalid yellow bowl phase')
    require(state['rest'] in ('not_started','resting','complete'), 'invalid batter rest phase')
    if state['wet_transferred']:
        require(state['dry'] == DRY and state['wet'] == WET, 'wet transfer requires exact dry and wet ingredients')
        require(state['yellow_bowl'] in ('film','emptied'), 'yellow cannot retain a duplicate wet mixture')
    if state['pairs_started']:
        require(state['wet_transferred'] and state['rest'] == 'complete', 'cooking requires one complete rested batter')
    if pending:
        require(state['stove'] == 'ON', 'uncooked pair cannot cook with burner off')
    if sum(state['served'].values()) or state['eaten_total']:
        require(state['stove'] == 'OFF' and state['cooked_total'] == 12 and state['table_ready'], 'serve only after all twelve are cooked and stove is off')
    if state['meal_finished']:
        require(state['eaten_total'] == 12 and state['tray'] == 0 and sum(state['served'].values()) == 0, 'finished meal must account for all twelve pancakes')
    return state


def apply_event(before, event):
    state = deepcopy(before)
    validate_state(state)
    kind = event['type']
    if kind == 'vase':
        state['vase_location'] = event['location']
    elif kind == 'wash_hands':
        state['hands_washed'] = True
    elif kind == 'add_dry':
        require(state['hands_washed'] and not state['wet_transferred'], 'dry measuring must precede wet transfer with clean hands')
        require(event['ingredient'] in DRY and event['amount'] > 0, 'dry additions must use positive recipe quantities')
        state['dry'][event['ingredient']] += event['amount']
        state['blue_bowl'] = 'dry'
    elif kind == 'split_butter':
        require(not state['butter_split'], 'butter may be allocated only once')
        state['butter_split'] = True
    elif kind == 'melt_butter':
        require(state['butter_split'], 'allocate three batter tablespoons before melting')
        state['butter_melted'] = True
    elif kind == 'cool_butter':
        require(state['butter_melted'], 'butter must melt before cooling')
        state['butter_cooled'] = True
    elif kind == 'add_wet':
        require(state['hands_washed'] and not state['wet_transferred'], 'wet measuring must precede transfer with clean hands')
        require(event['ingredient'] in WET and event['amount'] > 0, 'wet additions must use positive recipe quantities')
        if event['ingredient'] == 'butter_tbsp':
            require(state['butter_cooled'], 'batter butter must be cooled')
        state['wet'][event['ingredient']] += event['amount']
        state['yellow_bowl'] = 'wet'
    elif kind == 'transfer_wet':
        require(not state['wet_transferred'] and state['dry'] == DRY and state['wet'] == WET, 'transfer the complete wet mixture only once')
        state.update(wet_transferred=True, yellow_bowl='film', blue_bowl='batter')
    elif kind == 'scrape_yellow':
        require(state['yellow_bowl'] == 'film', 'scrape only the remaining wet film')
        state['yellow_bowl'] = 'emptied'
    elif kind == 'start_rest':
        require(state['wet_transferred'] and state['yellow_bowl'] == 'emptied' and state['rest'] == 'not_started', 'rest requires the complete single blue batter bowl')
        state['rest'] = 'resting'
    elif kind == 'finish_rest':
        require(state['rest'] == 'resting', 'five-minute story-time rest must begin before completion')
        state['rest'] = 'complete'
    elif kind == 'plates':
        require(state['plates_ready'] == 0, 'do not duplicate six plates')
        state['plates_ready'] = 6
    elif kind == 'set_table':
        require(state['plates_ready'] == 6, 'set exactly six places')
        state['table_ready'] = True
    elif kind == 'stove_on':
        require(state['rest'] == 'complete', 'preheat after the batter rest')
        state['stove'] = 'ON'
    elif kind == 'grease_pan':
        require(state['stove'] == 'ON' and state['butter_split'] and state['pan']['count'] == 0, 'grease warm empty skillet from the original reserve')
        state['pan_butter_sixths_remaining'] -= 1
    elif kind == 'pour_pair':
        require(state['stove'] == 'ON' and state['pan']['count'] == 0 and state['portions_remaining'] >= 2, 'pour only a pair into a warm empty pan')
        state['pairs_started'] += 1
        state['portions_remaining'] -= 2
        state['pan'] = {'count': 2, 'stage': 'first_side'}
    elif kind == 'flip_pair':
        require(state['pan']['stage'] == 'first_side', 'flip only after first-side cooking')
        state['pan']['stage'] = 'second_side'
    elif kind == 'finish_pair':
        require(state['pan']['stage'] == 'second_side', 'both sides must cook before completion')
        state['pan']['stage'] = 'cooked'
        state['pairs_completed'] += 1
        state['cooked_total'] += 2
    elif kind == 'transfer_pair':
        require(state['pan']['stage'] == 'cooked', 'never transfer raw pancakes to the clean tray')
        state['tray'] += 2
        state['pan'] = {'count': 0, 'stage': 'empty'}
    elif kind == 'cut_first':
        require(state['cooked_total'] >= 2 and not state['first_pancake_cut'], 'cut the cooked first pancake only once; halves still count as one')
        state['first_pancake_cut'] = True
    elif kind == 'stove_off':
        require(state['cooked_total'] == 12 and state['pan']['count'] == 0, 'finish all six pairs before shutting down')
        state['stove'] = 'OFF'
    elif kind == 'clear_raw':
        require(state['portions_remaining'] == 0 and state['wet_transferred'], 'do not erase unallocated batter')
        state.update(blue_bowl='empty_after_cooking', yellow_bowl='emptied')
    elif kind == 'serve':
        actor = event['actor']
        require(actor in CAST and state['served'][actor] == 0 and state['tray'] >= 2, 'serve two once to a known family member')
        state['served'][actor] = 2
        state['tray'] -= 2
    elif kind == 'start_meal':
        require(all(count == 2 for count in state['served'].values()), 'everyone receives two before the meal')
        state['meal_started'] = True
    elif kind == 'finish_meal':
        require(state['meal_started'] and all(count == 2 for count in state['served'].values()), 'meal ellipsis accounts for the six allocated servings')
        state.update(meal_finished=True, eaten_total=12, served={name: 0 for name in CAST}, dishware_cleared=True)
    else:
        raise ValueError(f'Unknown continuity event: {kind}')
    return validate_state(state)


def event(kind, **details):
    return {'type': kind, **details}


def events_for_shot(number):
    """Explicit ledger from CONTINUITY.md and the exact screenplay end states."""
    fixed = {
        3:[event('vase',location='island')],10:[event('vase',location='decoration_shelf')],
        21:[event('wash_hands')],23:[event('add_dry',ingredient='flour_cups',amount=1)],
        24:[event('add_dry',ingredient='flour_cups',amount=1)],25:[event('add_dry',ingredient='sugar_tbsp',amount=2)],
        27:[event('add_dry',ingredient='baking_powder_tbsp',amount=1)],28:[event('add_dry',ingredient='salt_tsp',amount=.5)],
        29:[event('split_butter')],30:[event('melt_butter')],31:[event('cool_butter')],
        32:[event('add_wet',ingredient='eggs',amount=2)],34:[event('add_wet',ingredient='milk_cups',amount=1.5)],
        36:[event('add_wet',ingredient='butter_tbsp',amount=3)],37:[event('transfer_wet')],38:[event('scrape_yellow')],
        41:[event('start_rest')],42:[event('plates')],43:[event('set_table')],45:[event('finish_rest')],
        46:[event('stove_on')],47:[event('grease_pan')],49:[event('pour_pair')],51:[event('flip_pair')],
        52:[event('finish_pair'),event('transfer_pair'),event('cut_first')],53:[event('grease_pan')],
        54:[event('pour_pair')],55:[event('flip_pair')],56:[event('finish_pair'),event('transfer_pair')],
        57:[event('grease_pan'),event('pour_pair'),event('flip_pair'),event('finish_pair'),event('transfer_pair')],
        59:[event('grease_pan'),event('pour_pair'),event('flip_pair'),event('finish_pair')],60:[event('transfer_pair')],
        61:[event('grease_pan'),event('pour_pair'),event('flip_pair'),event('finish_pair'),event('transfer_pair')],
        63:[event('grease_pan'),event('pour_pair')],64:[event('flip_pair'),event('finish_pair'),event('transfer_pair')],
        65:[event('stove_off')],66:[event('clear_raw')],69:[event('serve',actor='DAN')],
        70:[event('serve',actor='LEO'),event('serve',actor='ELLA')],
        71:[event('serve',actor='MAYA'),event('serve',actor='NINA'),event('serve',actor='MAX')],
        73:[event('start_meal')],79:[event('finish_meal')],
    }
    return deepcopy(fixed.get(number, []))


def apply_events(before, events):
    state = deepcopy(before)
    for item in events:
        state = apply_event(state, item)
    return validate_state(state)
