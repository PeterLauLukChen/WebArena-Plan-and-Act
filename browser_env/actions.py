"""
Browser Env action space.
Inspited by Farama-Foundation/miniwob-plusplus
"""
import ast
import random
import re
import string
from enum import IntEnum
from itertools import chain
from typing import Any, TypedDict, Union, cast
import time

import numpy as np
import numpy.typing as npt
from beartype import beartype
from beartype.door import is_bearable
from gymnasium import spaces
from playwright._impl._api_structures import ViewportSize
from playwright.async_api import BrowserContext as ABrowserContext
from playwright.async_api import Locator as ALocator
from playwright.async_api import Page as APage
from playwright.sync_api import BrowserContext, Locator, Page

from browser_env.constants import (
    ASCII_CHARSET,
    FREQ_UNICODE_CHARSET,
    MAX_ANSWER_LENGTH,
    MAX_ELEMENT_ID,
    MAX_ELEMENT_INDEX_IN_VIEWPORT,
    MAX_PAGE_NUMBER,
    MAX_VANILLA_STR_LENGTH,
    PLAYWRIGHT_ACTIONS,
    PLAYWRIGHT_LOCATORS,
    ROLES,
    SPECIAL_KEY_MAPPINGS,
    SPECIAL_KEYS,
    SPECIAL_LOCATORS,
    TEXT_MAX_LENGTH,
    TYPING_MAX_LENGTH,
    URL_MAX_LENGTH,
    RolesType,
)
from browser_env.processors import ObservationProcessor


class ParsedPlaywrightCode(TypedDict):
    function_name: str
    arguments: list[str]
    keywords: dict[str, Any]


from browser_env.processors import (
    ObservationProcessor,
    TextObervationProcessor,
)


@beartype
def is_in_viewport(
    element: Locator, viewport: ViewportSize, threshold: float = 0.3
) -> bool:
    """Given a playwright locator, check if it is in the viewport"""
    box = element.bounding_box()
    assert box is not None
    boxx0 = box["x"]
    boxx1 = box["x"] + box["width"]
    boxy0 = box["y"]
    boxy1 = box["y"] + box["height"]
    viewportx0, viewporty0 = 0, 0
    viewportx1, viewporty1 = viewport["width"], viewport["height"]
    inter = max(0, min(boxx1, viewportx1) - max(boxx0, viewportx0)) * max(
        0, min(boxy1, viewporty1) - max(boxy0, viewporty0)
    )
    ratio = inter / (box["width"] * box["height"])
    return ratio > threshold


@beartype
async def async_is_in_viewport(
    element: ALocator, viewport: ViewportSize, threshold: float = 0.3
) -> bool:
    box = await element.bounding_box()
    assert box is not None
    boxx0 = box["x"]
    boxx1 = box["x"] + box["width"]
    boxy0 = box["y"]
    boxy1 = box["y"] + box["height"]
    viewportx0, viewporty0 = 0, 0
    viewportx1, viewporty1 = viewport["width"], viewport["height"]
    inter = max(0, min(boxx1, viewportx1) - max(boxx0, viewportx0)) * max(
        0, min(boxy1, viewporty1) - max(boxy0, viewporty0)
    )
    ratio = inter / (box["width"] * box["height"])
    return ratio > threshold


class Action(TypedDict):
    action_type: int
    coords: npt.NDArray[np.float32]
    element_role: int
    element_name: str
    text: list[int]
    page_number: int
    url: str
    nth: int
    element_id: str
    direction: str
    key_comb: str
    pw_code: str
    answer: str
    raw_prediction: str  # raw prediction from the model


@beartype
def action2str(
    action: Action, action_set_tag: str, semantic_element: str = ""
) -> str:
    """Return the string representation of an action

    sementic_element: the semantic information of the element
    such as a line in an accessibility tree
    """
    if action_set_tag in [
        "id_accessibility_tree",
        "id_accessibility_tree_with_captioner",
    ]:
        element_id = action["element_id"]
        match action["action_type"]:
            case ActionTypes.CLICK:
                # [ID=X] xxxxx
                action_str = f"click [{element_id}] where [{element_id}] is {semantic_element}"
            case ActionTypes.TYPE:
                text = "".join([_id2key[i] for i in action["text"]])
                action_str = f"type [{element_id}] [{text}] where [{element_id}] is {semantic_element}"
            case ActionTypes.HOVER:
                action_str = f"hover [{element_id}] where [{element_id}] is {semantic_element}"
            case ActionTypes.SCROLL:
                action_str = f"scroll [{action['direction']}]"
            case ActionTypes.KEY_PRESS:
                action_str = f"press [{action['key_comb']}]"
            case ActionTypes.GOTO_URL:
                action_str = f"goto [{action['url']}]"
            case ActionTypes.NEW_TAB:
                action_str = "new_tab"
            case ActionTypes.PAGE_CLOSE:
                action_str = "close_tab"
            case ActionTypes.GO_BACK:
                action_str = "go_back"
            case ActionTypes.GO_FORWARD:
                action_str = "go_forward"
            case ActionTypes.PAGE_FOCUS:
                action_str = f"page_focus [{action['page_number']}]"
            case ActionTypes.CLEAR:
                action_str = f"clear [{element_id}] where [{element_id}] is {semantic_element}"
            case ActionTypes.STOP:
                action_str = f"stop [{action['answer']}]"
            case ActionTypes.NONE:
                action_str = "none"
            case _:
                raise ValueError(
                    f"Unknown action type {action['action_type']}"
                )
    elif action_set_tag == "som":
        element_id = action["element_id"]
        match action["action_type"]:
            case ActionTypes.CLICK:
                # [ID=X] xxxxx
                action_str = f"click [{element_id}] where [{element_id}]"
            case ActionTypes.CLEAR:
                action_str = f"clear [{element_id}] where [{element_id}] is {semantic_element}"
            case ActionTypes.TYPE:
                text = "".join([_id2key[i] for i in action["text"]])
                action_str = (
                    f"type [{element_id}] [{text}] where [{element_id}]"
                )
            case ActionTypes.HOVER:
                action_str = f"hover [{element_id}] where [{element_id}]"
            case ActionTypes.SCROLL:
                action_str = f"scroll [{action['direction']}]"
            case ActionTypes.KEY_PRESS:
                action_str = f"press [{action['key_comb']}]"
            case ActionTypes.GOTO_URL:
                action_str = f"goto [{action['url']}]"
            case ActionTypes.NEW_TAB:
                action_str = "new_tab"
            case ActionTypes.PAGE_CLOSE:
                action_str = "close_tab"
            case ActionTypes.GO_BACK:
                action_str = "go_back"
            case ActionTypes.GO_FORWARD:
                action_str = "go_forward"
            case ActionTypes.PAGE_FOCUS:
                action_str = f"page_focus [{action['page_number']}]"
            case ActionTypes.STOP:
                action_str = f"stop [{action['answer']}]"
            case ActionTypes.NONE:
                action_str = "none"
            case _:
                raise ValueError(
                    f"Unknown action type {action['action_type']}"
                )
    else:
        raise NotImplementedError(f"Unknown action set tag {action_set_tag}")

    return action_str


def action2create_function(action: Action) -> str:
    match (action["action_type"]):
        case ActionTypes.NONE:
            return "create_none_action()"
        # mouse wheel and keyboard action
        case ActionTypes.SCROLL:
            direction = "up" if "up" in action["direction"] else "down"
            return f"create_scroll_action({repr(direction)})"
        case ActionTypes.KEY_PRESS:
            return f"create_key_press_action({repr(action['key_comb'])})"
        # inter-page actions
        case ActionTypes.PAGE_FOCUS:
            return f"create_page_focus_action({action['page_number']})"
        case ActionTypes.NEW_TAB:
            return "create_new_tab_action()"
        case ActionTypes.GO_BACK:
            return "create_go_back_action()"
        case ActionTypes.GO_FORWARD:
            return "create_go_forward_action()"
        case ActionTypes.GOTO_URL:
            return f"create_goto_url_action({repr(action['url'])})"
        case ActionTypes.PAGE_CLOSE:
            return "create_page_close_action()"

        # low-level keyboard and mouse actions
        case ActionTypes.MOUSE_CLICK:
            return f"create_mouse_click_action({action['coords'][0]}, {action['coords'][1]})"
        case ActionTypes.MOUSE_HOVER:
            return f"create_mouse_hover_action({action['coords'][0]}, {action['coords'][1]})"
        case ActionTypes.KEYBOARD_TYPE:
            return f"create_keyboard_type_action({list(map(lambda x: _id2key[x], action['text']))})"

        # mid-level keyboard and mouse actions
        case ActionTypes.CLICK:
            args = []
            args.append(f"element_id={repr(action['element_id'])}")
            args.append(
                f"element_role={repr(_id2role[action['element_role']])}"
            )
            args.append(f"element_name={repr(action['element_name'])}")
            args.append(f"pw_code={repr(action['pw_code'])}")
            args_str = ", ".join(args)
            return f"create_click_action({args_str})"
        case ActionTypes.CLEAR:
            args = []
            args.append(f"element_id={repr(action['element_id'])}")
            args.append(
                f"element_role={repr(_id2role[action['element_role']])}"
            )
            args.append(f"element_name={repr(action['element_name'])}")
            args.append(f"pw_code={repr(action['pw_code'])}")
            args_str = ", ".join(args)
            return f"create_clear_action({args_str})"
        case ActionTypes.HOVER:
            args = []
            args.append(f"element_id={repr(action['element_id'])}")
            args.append(
                f"element_role={repr(_id2role[action['element_role']])}"
            )
            args.append(f"element_name={repr(action['element_name'])}")
            args.append(f"pw_code={repr(action['pw_code'])}")
            args_str = ", ".join(args)
            return f"create_hover_action({args_str})"
        case ActionTypes.TYPE:
            args = []
            text = "".join(map(lambda x: _id2key[x], action["text"]))
            args.append(f"text={repr(text)}")
            args.append(f"element_id={repr(action['element_id'])}")
            args.append(
                f"element_role={repr(_id2role[action['element_role']])}"
            )
            args.append(f"element_name={repr(action['element_name'])}")
            args.append(f"pw_code={repr(action['pw_code'])}")
            args_str = ", ".join(args)
            return f"create_type_action({args_str})"

        # high-level actions, only support locators from playwright
        case ActionTypes.CHECK:
            return f"create_check_action(pw_code={repr(action['pw_code'])})"
        case ActionTypes.SELECT_OPTION:
            return f"create_select_option_action(pw_code={repr(action['pw_code'])})"
        case ActionTypes.STOP:
            return f'create_stop_action({repr(action["answer"])})'

    raise ValueError(f"Invalid action type: {action['action_type']}")


class ActionTypes(IntEnum):
    """Valid action types for browser env."""

    NONE = 0
    # mouse wheel and keyboard, universal across all action spaces
    SCROLL = 1
    KEY_PRESS = 2

    # low level mouse and keyboard actions
    MOUSE_CLICK = 3
    KEYBOARD_TYPE = 4
    MOUSE_HOVER = 5

    # mid level mouse and keyboard actions
    CLICK = 6
    TYPE = 7
    HOVER = 8

    # page level actions, universal across all action spaces
    PAGE_FOCUS = 9
    NEW_TAB = 10
    GO_BACK = 11
    GO_FORWARD = 12
    GOTO_URL = 13
    PAGE_CLOSE = 14

    # high-leval actions that playwright support
    CHECK = 15
    SELECT_OPTION = 16

    STOP = 17
    CLEAR = 18
    
    # webrl actions
    SEARCH = 19
    SELECT_DROPDOWN_OPTION = 20

    def __str__(self) -> str:
        return f"ACTION_TYPES.{self.name}"


@beartype
def is_equivalent(a: Action, b: Action) -> bool:
    """Return True if two actions are equal."""
    if a["action_type"] != b["action_type"]:
        return False
    match (a["action_type"]):
        case ActionTypes.NONE:
            return True
        case ActionTypes.SCROLL:
            da = "up" if "up" in a["direction"] else "down"
            db = "up" if "up" in b["direction"] else "down"
            return da == db
        case ActionTypes.KEY_PRESS:
            return a["key_comb"] == b["key_comb"]
        case ActionTypes.MOUSE_CLICK | ActionTypes.MOUSE_HOVER:
            return np.allclose(a["coords"], b["coords"])
        case ActionTypes.KEYBOARD_TYPE:
            return a["text"] == b["text"]
        case ActionTypes.CLICK | ActionTypes.HOVER | ActionTypes.TYPE:  # TODO: can be further optimized
            if a["element_id"] and b["element_id"]:
                return a["element_id"] == b["element_id"]
            elif a["element_role"] and b["element_role"]:
                return (
                    a["element_role"] == b["element_role"]
                    and a["element_name"] == b["element_name"]
                )
            elif a["pw_code"] and b["pw_code"]:
                return a["pw_code"] == b["pw_code"]
            else:
                return False
        case ActionTypes.PAGE_FOCUS:
            return a["page_number"] == b["page_number"]
        case ActionTypes.NEW_TAB:
            return True
        case ActionTypes.GO_BACK:
            return True
        case ActionTypes.GO_FORWARD:
            return True
        case ActionTypes.GOTO_URL:
            return a["url"] == b["url"]
        case ActionTypes.PAGE_CLOSE:
            return True
        case ActionTypes.CHECK | ActionTypes.SELECT_OPTION:
            return a["pw_code"] == b["pw_code"]
        case ActionTypes.STOP:
            return a["answer"] == b["answer"]
        case _:
            raise ValueError(f"Unknown action type: {a['action_type']}")


_key2id: dict[str, int] = {
    key: i
    for i, key in enumerate(
        chain(SPECIAL_KEYS, ASCII_CHARSET, FREQ_UNICODE_CHARSET, ["\n"])
    )
}
_id2key: list[str] = sorted(_key2id, key=_key2id.get)  # type: ignore[arg-type]
_role2id: dict[RolesType, int] = {
    cast(RolesType, role): i
    for i, role in enumerate(chain(ROLES, SPECIAL_LOCATORS))
}
_id2role: list[RolesType] = sorted(_role2id, key=_role2id.get)  # type: ignore[arg-type]


@beartype
def _keys2ids(keys: list[int | str] | str) -> list[int]:
    return list(
        map(
            lambda key: _key2id.get(str(key), _key2id.get(key, " "))
            if is_bearable(key, str)
            else int(key),
            keys,
        )
    )


def get_action_space() -> spaces.Dict:
    """Return the space of serialized actions."""
    space = spaces.Dict(
        {
            "action_type": spaces.Discrete(len(ActionTypes)),
            # coords (left, top) is used for COORD_CLICK
            "coords": spaces.Box(
                np.array([0.0, 0.0], dtype=np.float32),
                np.array([1.0, 1.0], dtype=np.float32),
            ),
            # element role is used for FOCUS_AND_CLICK and FOCUS_AND_TYPE
            "element_role": spaces.Discrete(
                len(ROLES) + len(SPECIAL_LOCATORS)
            ),
            # element name is used with element role
            "element_name": spaces.Text(TEXT_MAX_LENGTH),
            "element_id": spaces.Text(TEXT_MAX_LENGTH),
            # text is only used for TYPE and FOCUS_AND_TYPE
            "text": spaces.MultiDiscrete(
                [
                    len(ASCII_CHARSET)
                    + len(SPECIAL_KEYS)
                    + len(FREQ_UNICODE_CHARSET)
                ]
                * TYPING_MAX_LENGTH
            ),
            "page_number": spaces.Discrete(MAX_PAGE_NUMBER),
            "url": spaces.Text(URL_MAX_LENGTH),
            "nth": spaces.Discrete(MAX_ELEMENT_INDEX_IN_VIEWPORT),
            "key_comb": spaces.Text(MAX_VANILLA_STR_LENGTH),
            "direction": spaces.Text(MAX_VANILLA_STR_LENGTH),
            "pw_code": spaces.Text(MAX_VANILLA_STR_LENGTH),
            "answer": spaces.Text(MAX_ANSWER_LENGTH),
        }
    )
    return space


def create_random_action() -> Action:
    """Return a random action."""
    return {
        "action_type": np.random.randint(len(ActionTypes)),
        "coords": np.random.rand(2).astype(np.float32),
        "element_role": np.random.randint(len(ROLES) + len(SPECIAL_LOCATORS)),
        "element_name": "".join(
            random.choices(ASCII_CHARSET, k=np.random.randint(TEXT_MAX_LENGTH))
        ),
        "text": list(
            random.choices(
                list(range(len(ASCII_CHARSET))),
                k=np.random.randint(TYPING_MAX_LENGTH),
            )
        ),
        "page_number": np.random.randint(MAX_PAGE_NUMBER),
        "url": "".join(
            random.choices(ASCII_CHARSET, k=np.random.randint(URL_MAX_LENGTH))
        ),
        "nth": np.random.randint(MAX_ELEMENT_INDEX_IN_VIEWPORT),
        "element_id": str(np.random.randint(MAX_ELEMENT_ID)),
        "key_comb": "+".join(
            random.choices(SPECIAL_KEYS, k=np.random.randint(3))
        ),
        "direction": random.choice(["up", "down"]),
        "pw_code": "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=np.random.randint(MAX_VANILLA_STR_LENGTH),
            )
        ),
        "answer": str(np.random.randint(MAX_ANSWER_LENGTH)),
        "raw_prediction": str(np.random.randint(MAX_ANSWER_LENGTH)),
    }


@beartype
def create_none_action() -> Action:
    """Return a valid action object that does nothing."""
    return {
        "action_type": ActionTypes.NONE,
        "coords": np.zeros(2, dtype=np.float32),
        "element_role": 0,
        "element_name": "",
        "text": [],
        "page_number": 0,
        "url": "",
        "nth": 0,
        "pw_code": "",  # str that requires further processing
        "element_id": "",
        "key_comb": "",
        "direction": "",
        "answer": "",
        "raw_prediction": "",
    }


@beartype
def create_stop_action(answer: str) -> Action:
    action = create_none_action()
    action.update({"action_type": ActionTypes.STOP, "answer": answer})
    return action


@beartype
def create_scroll_action(direction: str) -> Action:
    """Return the playwright action"""
    assert direction in ["up", "down"]
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.SCROLL,
            "direction": direction,
        }
    )
    return action


@beartype
def create_mouse_hover_action(
    left: float | None = None, top: float | None = None
) -> Action:
    """Return a valid action object with type COORD_CLICK."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.MOUSE_HOVER,
            "coords": np.array([left, top], dtype=np.float32),
        }
    )
    return action


@beartype
def create_key_press_action(key_comb: str) -> Action:
    """Return the key press action"""

    def map_keys(key_comb: str) -> str:
        keys = key_comb.split("+")
        mapped_keys = []
        for key in keys:
            mapped_key = SPECIAL_KEY_MAPPINGS.get(key.lower(), key)
            mapped_keys.append(mapped_key)
        return "+".join(mapped_keys)

    action = create_none_action()
    mapped_key_comb = map_keys(key_comb)
    action.update(
        {
            "action_type": ActionTypes.KEY_PRESS,
            "key_comb": mapped_key_comb,
        }
    )
    return action


@beartype
def create_page_focus_action(page_number: int) -> Action:
    """Return a valid action object with type PAGE_FOCUS."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.PAGE_FOCUS,
            "page_number": page_number,
        }
    )
    return action


@beartype
def create_new_tab_action() -> Action:
    """Return a valid action object with type NEW_TAB."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.NEW_TAB,
        }
    )
    return action


@beartype
def create_go_back_action() -> Action:
    """Return a valid action object with type GO_BACK."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.GO_BACK,
        }
    )
    return action


@beartype
def create_go_forward_action() -> Action:
    """Return a valid action object with type GO_FORWARD."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.GO_FORWARD,
        }
    )
    return action


@beartype
def create_goto_url_action(url: str) -> Action:
    """Return a valid action object with type GOTO_URL."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.GOTO_URL,
            "url": url,
        }
    )
    return action


@beartype
def create_page_close_action() -> Action:
    """Return a valid action object with type PAGE_CLOSE."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.PAGE_CLOSE,
        }
    )
    return action


@beartype
def create_mouse_click_action(
    left: float | None = None, top: float | None = None
) -> Action:
    """Return a valid action object with type COORD_CLICK."""
    action = create_none_action()
    if left and top:
        action.update(
            {
                "action_type": ActionTypes.MOUSE_CLICK,
                "coords": np.array([left, top], dtype=np.float32),
            }
        )
    elif (not left) and (not top):
        action.update(
            {
                "action_type": ActionTypes.CLICK,
            }
        )
    else:
        raise ValueError("left and top must be both None or both not None")
    return action


@beartype
def create_clear_action(
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.CLEAR,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_keyboard_type_action(keys: list[int | str] | str) -> Action:
    """Return a valid action object with type TYPE."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.KEYBOARD_TYPE,
            "text": _keys2ids(keys),
        }
    )
    return action


@beartype
def create_click_action(
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.CLICK,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_hover_action(
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.HOVER,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_type_action(
    text: str,
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.TYPE,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "text": _keys2ids(text),
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_type_action_webrl(
    text: str,
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.TYPE,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "text": text,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_search_action(
    text: str,
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.SEARCH,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "text": text,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_select_dropdown_option_action(
    argument: str,
    element_id: str = "",
    element_role: RolesType = "link",
    element_name: str = "",
    pw_code: str = "",
    nth: int = 0,
) -> Action:
    """Return a valid action object with type SELECT_DROPDOWN_OPTION."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.SELECT_DROPDOWN_OPTION,
            "element_id": element_id,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
            "argument": argument,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_check_action(pw_code: str) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.CHECK,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_select_option_action(
    pw_code: str,
) -> Action:
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.SELECT_OPTION,
            "pw_code": pw_code,
        }
    )
    return action


@beartype
def create_focus_action(
    element_role: RolesType, element_name: str = "", nth: int = 0
) -> Action:
    """Return a valid action object with type CLICK.

    Keep compatible with the old version."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.CLICK,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
        }
    )
    return action


@beartype
def create_focus_and_click_action(
    element_role: RolesType, element_name: str = "", nth: int = 0
) -> Action:
    """Return a valid action object with type CLICK.

    Keep compatible with the old version."""

    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.CLICK,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "nth": nth,
        }
    )
    return action


@beartype
def create_focus_and_type_action(
    keys: list[int | str] | str,
    element_role: RolesType,
    element_name: str = "",
    nth: int = 0,
) -> Action:
    """Return a valid action object with type TYPE.

    Keep compatible with the old version."""
    action = create_none_action()
    action.update(
        {
            "action_type": ActionTypes.TYPE,
            "element_role": _role2id[element_role],
            "element_name": element_name,
            "text": _keys2ids(keys),
            "nth": nth,
        }
    )
    return action


@beartype
def execute_scroll(direction: str, page: Page) -> None:
    # perform the action
    # code from natbot
    if direction == "up":
        page.evaluate(
            "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop - window.innerHeight;"
        )
    elif direction == "down":
        page.evaluate(
            "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop + window.innerHeight;"
        )

@beartype
def execute_scroll_webrl(direction: str, page: Page) -> None:
    # perform the action which move 2/3 of the height of the page at a time
    if direction == "up":
        page.mouse.wheel(0, -page.viewport_size['height'] * 2.0 / 3)
    elif direction == "down":
        page.mouse.wheel(0, page.viewport_size['height'] * 2.0 / 3)

@beartype
async def aexecute_scroll(direction: str, page: APage) -> None:
    # perform the action
    # code from natbot
    if direction == "up":
        await page.evaluate(
            "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop - window.innerHeight;"
        )
    elif direction == "down":
        await page.evaluate(
            "(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop + window.innerHeight;"
        )


@beartype
def execute_key_press(key: str, page: Page) -> None:
    """Press a key."""
    if "Meta" in key and "Mac" not in page.evaluate("navigator.platform"):
        key = key.replace("Meta", "Control")
    page.keyboard.press(key)


@beartype
async def aexecute_key_press(key: str, page: APage) -> None:
    """Press a key."""
    if "Meta" in key and "Mac" not in await page.evaluate(
        "navigator.platform"
    ):
        key = key.replace("Meta", "Control")
    await page.keyboard.press(key)


@beartype
def execute_mouse_hover(left: float, top: float, page: Page) -> None:
    """Click at coordinates (left, top)."""
    viewport_size = page.viewport_size
    assert viewport_size
    page.mouse.move(
        left * viewport_size["width"], top * viewport_size["height"]
    )


@beartype
async def aexecute_mouse_hover(left: float, top: float, page: APage) -> None:
    """Click at coordinates (left, top)."""
    viewport_size = page.viewport_size
    assert viewport_size
    await page.mouse.move(
        left * viewport_size["width"], top * viewport_size["height"]
    )


def execute_mouse_click(left: float, top: float, page: Page) -> None:
    """Click at coordinates (left, top)."""
    viewport_size = page.viewport_size
    assert viewport_size
    page.mouse.click(
        left * viewport_size["width"], top * viewport_size["height"]
    )


@beartype
async def aexecute_mouse_click(left: float, top: float, page: APage) -> None:
    """Click at coordinates (left, top)."""
    viewport_size = page.viewport_size
    assert viewport_size
    await page.mouse.click(
        left * viewport_size["width"], top * viewport_size["height"]
    )


@beartype
def execute_keyboard_type(text: str, page: Page) -> None:
    """Fill the focused element with text."""
    page.keyboard.type(text)


@beartype
async def aexecute_keyboard_type(text: str, page: APage) -> None:
    """Fill the focused element with text."""
    await page.keyboard.type(text)


@beartype
def execute_click_current(page: Page) -> None:
    """Click at the current mouse position."""
    locators = page.locator("*:focus")
    if not locators.count():
        for frame in page.frames[1:]:
            locators = frame.locator("*:focus")
            if locators.count():
                break
    locators.click()


@beartype
async def aexecute_click_current(page: APage) -> None:
    """Click at the current mouse position."""
    locators = page.locator("*:focus")
    locator_count = await locators.count()
    if not locator_count:
        for frame in page.frames[1:]:
            locators = frame.locator("*:focus")
            locator_count = await locators.count()
            if locator_count:
                break
    await locators.click()
    await page.wait_for_load_state("load")


@beartype
def execute_type(keys: list[int], page: Page) -> None:
    """Send keystrokes to the focused element."""
    text = "".join([_id2key[key] for key in keys])
    page.keyboard.type(text)


@beartype
async def aexecute_type(keys: list[int], page: APage) -> None:
    """Send keystrokes to the focused element."""
    text = "".join([_id2key[key] for key in keys])
    await page.keyboard.type(text)


@beartype
def execute_focus(
    element_role: int, element_name: str, nth: int, page: Page
) -> None:
    """Click the specified DOM element."""
    element_role_str = _id2role[element_role]
    if page.viewport_size is None:
        raise ValueError("Viewport size is not set for the current page")
    element_location_list: list[tuple[Locator, float, float]] = []
    for frame in page.frames:
        match element_role_str:
            case "alt_text":
                locators = frame.get_by_alt_text(element_name)
            case "label":
                locators = frame.get_by_label(element_name)
            case "placeholder":
                locators = frame.get_by_placeholder(element_name)
            case _:
                locators = frame.get_by_role(
                    role=element_role_str, name=element_name
                )
        for locator_idx in range(locators.count()):
            locator = locators.nth(locator_idx)
            if is_in_viewport(locator, page.viewport_size):
                bounding_box = locator.bounding_box()
                assert bounding_box
                element_location_list.append(
                    (locator, bounding_box["x"], bounding_box["y"])
                )
    if len(element_location_list) <= nth:
        raise ValueError(
            f"There are only {len(element_location_list)} elements found in viewport, but {nth + 1} is requested"
        )
    element_location_list.sort(key=lambda x: (x[2], x[1]))  # row major order
    element_location_list[nth][0].focus()


@beartype
async def aexecute_focus(
    element_role: int, element_name: str, nth: int, page: APage
) -> None:
    """Click the specified DOM element."""
    element_role_str = _id2role[element_role]
    if page.viewport_size is None:
        raise ValueError("Viewport size is not set for the current page")
    element_location_list: list[tuple[ALocator, float, float]] = []
    for frame in page.frames:
        match element_role_str:
            case "alt_text":
                locators = frame.get_by_alt_text(element_name)
            case "label":
                locators = frame.get_by_label(element_name)
            case "placeholder":
                locators = frame.get_by_placeholder(element_name)
            case _:
                locators = frame.get_by_role(
                    role=element_role_str, name=element_name
                )
        for locator_idx in range(await locators.count()):
            locator = locators.nth(locator_idx)
            if await async_is_in_viewport(locator, page.viewport_size):
                bounding_box = await locator.bounding_box()
                assert bounding_box
                element_location_list.append(
                    (locator, bounding_box["x"], bounding_box["y"])
                )
    if len(element_location_list) <= nth:
        raise ValueError(
            f"There are only {len(element_location_list)} elements found in viewport, but {nth + 1} is requested"
        )
    element_location_list.sort(key=lambda x: (x[2], x[1]))  # row major order
    await element_location_list[nth][0].focus()


@beartype
def locate(locator_calls: list[ParsedPlaywrightCode], page: Page) -> Locator:
    locator = page
    for call in locator_calls:
        function_name = call["function_name"]
        arguments = call["arguments"]
        keywords = call["keywords"]
        locator = getattr(locator, function_name)(*arguments, **keywords)
    return locator  # type: ignore[return-value]


@beartype
async def alocate(
    locator_calls: list[ParsedPlaywrightCode], page: APage
) -> ALocator:
    locator = page
    for call in locator_calls:
        function_name = call["function_name"]
        arguments = call["arguments"]
        keywords = call["keywords"]
        locator = await getattr(locator, function_name)(*arguments, **keywords)
    return locator  # type: ignore[return-value]


@beartype
def execute_playwright_click(
    locator_code: list[ParsedPlaywrightCode],
    page: Page,
    pw_action_args: list[str] = [],
    pw_action_kwargs: dict[str, Any] = {},
) -> None:
    locator = locate(locator_code, page)

    # perform the action
    locator.click(*pw_action_args, **pw_action_kwargs)


@beartype
async def aexecute_playwright_click(
    locator_code: list[ParsedPlaywrightCode],
    page: APage,
    pw_action_args: list[str] = [],
    pw_action_kwargs: dict[str, Any] = {},
) -> None:
    locator = await alocate(locator_code, page)

    # perform the action
    await locator.click(*pw_action_args, **pw_action_kwargs)


@beartype
def execute_playwright_hover(
    locator_code: list[ParsedPlaywrightCode], page: Page
) -> None:
    locator = locate(locator_code, page)

    # perform the action
    locator.hover()


@beartype
async def aexecute_playwright_hover(
    locator_code: list[ParsedPlaywrightCode], page: APage
) -> None:
    locator = await alocate(locator_code, page)

    # perform the action
    await locator.hover()


@beartype
def execute_playwright_type(
    text: str,
    locator_code: list[ParsedPlaywrightCode],
    page: Page,
    pw_action_args: list[str] = [],
    pw_action_kwargs: dict[str, Any] = {},
) -> None:
    locator = locate(locator_code, page)
    # perform the action
    pw_action_args = [text] + pw_action_args  # text is the first argument
    locator.type(*pw_action_args, **pw_action_kwargs)


@beartype
async def aexecute_playwright_type(
    text: str,
    locator_code: list[ParsedPlaywrightCode],
    page: APage,
    pw_action_args: list[str] = [],
    pw_action_kwargs: dict[str, Any] = {},
) -> None:
    locator = await alocate(locator_code, page)
    # perform the action
    pw_action_args = [text] + pw_action_args  # text is the first argument
    await locator.type(*pw_action_args, **pw_action_kwargs)


@beartype
def execute_playwright_select_option(
    locator_code: list[ParsedPlaywrightCode],
    page: Page,
    pw_action_args: list[str] = [],
    pw_action_kwargs: dict[str, Any] = {},
) -> None:
    locator = locate(locator_code, page)
    # perform the action
    locator.select_option(*pw_action_args, **pw_action_kwargs)


@beartype
async def aexecute_playwright_select_option(
    locator_code: list[ParsedPlaywrightCode],
    page: APage,
    pw_action_args: list[str] = [],
    pw_action_kwargs: dict[str, Any] = {},
) -> None:
    locator = await alocate(locator_code, page)
    # perform the action
    await locator.select_option(*pw_action_args, **pw_action_kwargs)


@beartype
def execute_playwright_check(
    locator_code: list[ParsedPlaywrightCode], page: Page
) -> None:
    locator = locate(locator_code, page)
    # perform the action
    locator.check()


@beartype
async def aexecute_playwright_check(
    locator_code: list[ParsedPlaywrightCode], page: APage
) -> None:
    locator = await alocate(locator_code, page)
    # perform the action
    await locator.check()


@beartype
def execute_action_webrl(
    action: Action,
    page: Page,
    browser_ctx: BrowserContext,
    obseration_processor: ObservationProcessor,
    sleep_after_execution: float = 0.0,
) -> Page:
    """Execute the action on the ChromeDriver."""
    action_type = action["action_type"]
    num_tabs_before = len(browser_ctx.pages)
    match action_type:
        case ActionTypes.NONE:
            pass
        case ActionTypes.SCROLL:
            direction = "up" if "up" in action["direction"] else "down"
            execute_scroll_webrl(direction, page)
        case ActionTypes.KEY_PRESS:
            keys = action["key_comb"]
            execute_key_press(keys, page)
        case ActionTypes.MOUSE_CLICK:
            execute_mouse_click(action["coords"][0], action["coords"][1], page)
        case ActionTypes.CLICK:
            # check each kind of locator in order
            # TODO[shuyanzh]: order is temp now
            element_id = action["element_id"]
            element_center = obseration_processor.get_element_center(element_id, page)  # type: ignore[attr-defined]
            execute_mouse_click(element_center[0], element_center[1], page)
        case ActionTypes.HOVER:
            element_id = action["element_id"]
            element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
            execute_mouse_hover(element_center[0], element_center[1], page)
        case ActionTypes.TYPE:
            element_id = action["element_id"]
            element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
            execute_mouse_click(element_center[0], element_center[1], page)
            # Clear the input field before typing
            execute_key_press("Meta+A", page)
            execute_key_press("Backspace", page)
            text = _keys2ids(action["text"])
            execute_type(text, page)
            page.keyboard.press("Enter")
        case ActionTypes.SEARCH:
            element_id = action["element_id"]
            element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
            execute_mouse_click(element_center[0], element_center[1], page)
            execute_key_press("Meta+A", page)
            execute_key_press('Backspace', page)
            text = _keys2ids(action["text"])
            execute_type(text, page)
            page.keyboard.press("Enter")
        case ActionTypes.GO_BACK:
            page.go_back()
        case ActionTypes.GO_FORWARD:
            page.go_forward()
        case ActionTypes.GOTO_URL:
            page.goto(action["url"])
        case ActionTypes.SELECT_DROPDOWN_OPTION:
            # Click
            element_id = action["element_id"]
            argument = action["argument"]
            element_center = obseration_processor.get_element_center(element_id, page)  # type: ignore[attr-defined]
            execute_mouse_click(element_center[0], element_center[1], page)
            # get element
            device_pixel_ratio = page.evaluate("window.devicePixelRatio")
            center_x, center_y = element_center[0] * page.viewport_size["width"], element_center[1] * page.viewport_size["height"]
            last_turn_element = page.evaluate_handle(f"""() => document.elementFromPoint({center_x / device_pixel_ratio}, {center_y / device_pixel_ratio})""")
            # get select element options
            select_element_options = [{"value": option.get_attribute('value'), "text": option.text_content().strip(' \n')} for option in
                    last_turn_element.query_selector_all("option")]
            selector_option_dict = dict((o["text"].lower(), o["value"]) for o in select_element_options)
            value = None
            for key in selector_option_dict.keys():
                if argument.lower() in key.lower():
                    value = selector_option_dict[key]
                    break
            if value is not None:
                last_turn_element.select_option(value=value)
        case _:
            raise ValueError(f"Unknown action type: {action_type}")
            
    page.wait_for_timeout(int(sleep_after_execution * 1000))
    num_tabs_now = len(browser_ctx.pages)
    # if a new tab is opened by clicking, switch to the new tab
    if num_tabs_now > num_tabs_before:
        page = browser_ctx.pages[-1]
        page.bring_to_front()

    return page

@beartype
def execute_action(
    action: Action,
    page: Page,
    browser_ctx: BrowserContext,
    obseration_processor: ObservationProcessor,
    sleep_after_execution: float = 0.0,
) -> Page:
    """Execute the action on the ChromeDriver."""
    action_type = action["action_type"]
    num_tabs_before = len(browser_ctx.pages)
    match action_type:
        case ActionTypes.NONE:
            pass

        case ActionTypes.SCROLL:
            direction = "up" if "up" in action["direction"] else "down"
            execute_scroll(direction, page)
        case ActionTypes.KEY_PRESS:
            keys = action["key_comb"]
            execute_key_press(keys, page)

        case ActionTypes.MOUSE_CLICK:
            execute_mouse_click(action["coords"][0], action["coords"][1], page)
        case ActionTypes.CLEAR:
            element_id = action["element_id"]
            element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
            execute_mouse_click(element_center[0], element_center[1], page)
            execute_key_press("Meta+A", page)
            execute_key_press("Backspace", page)
        case ActionTypes.MOUSE_HOVER:
            execute_mouse_hover(action["coords"][0], action["coords"][1], page)
        case ActionTypes.KEYBOARD_TYPE:
            execute_type(action["text"], page)
            page.keyboard.press("Enter")
        case ActionTypes.CLICK:
            # check each kind of locator in order
            # TODO[shuyanzh]: order is temp now
            if action["element_id"]:
                element_id = action["element_id"]
                element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
                execute_mouse_click(element_center[0], element_center[1], page)
            elif action["element_role"] and action["element_name"]:
                element_role = int(action["element_role"])
                element_name = action["element_name"]
                nth = action["nth"]
                execute_focus(element_role, element_name, nth, page)
                execute_type(action["text"], page)
                page.keyboard.press("Enter")
            elif action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                # [shuyanzh], don't support action args and kwargs now
                execute_playwright_type(
                    text=text, locator_code=locator_code, page=page
                )
                page.keyboard.press("Enter")
            else:
                raise ValueError("No proper locator found for click action")
        case ActionTypes.HOVER:
            if action["element_id"]:
                element_id = action["element_id"]
                element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
                execute_mouse_hover(element_center[0], element_center[1], page)
            elif action["element_role"] and action["element_name"]:
                element_role = int(action["element_role"])
                element_name = action["element_name"]
                nth = action["nth"]
                execute_focus(element_role, element_name, nth, page)
                execute_type(action["text"], page)
                page.keyboard.press("Enter")
            elif action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                # [shuyanzh], don't support action args and kwargs now
                execute_playwright_type(
                    text=text, locator_code=locator_code, page=page
                )
                page.keyboard.press("Enter")
            else:
                raise NotImplementedError(
                    "No proper locator found for hover action"
                )
        case ActionTypes.TYPE:
            if action["element_id"]:
                element_id = action["element_id"]
                element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
                execute_mouse_click(element_center[0], element_center[1], page)
                # Clear the input field before typing
                execute_key_press("Meta+A", page)
                execute_key_press("Backspace", page)
                execute_type(action["text"], page)
                page.keyboard.press("Enter")
            elif action["element_role"] and action["element_name"]:
                element_role = int(action["element_role"])
                element_name = action["element_name"]
                nth = action["nth"]
                execute_focus(element_role, element_name, nth, page)
                execute_type(action["text"], page)
                page.keyboard.press("Enter")
            elif action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                text = parsed_code[-1]["arguments"][0]
                # [shuyanzh], don't support action args and kwargs now
                execute_playwright_type(
                    text=text, locator_code=locator_code, page=page
                )
                page.keyboard.press("Enter")
            else:
                raise NotImplementedError(
                    "No proper locator found for type action"
                )

        case ActionTypes.PAGE_FOCUS:
            page = browser_ctx.pages[action["page_number"]]
            page.bring_to_front()
        case ActionTypes.NEW_TAB:
            page = browser_ctx.new_page()
        case ActionTypes.GO_BACK:
            page.go_back()
        case ActionTypes.GO_FORWARD:
            page.go_forward()
        case ActionTypes.GOTO_URL:
            page.goto(action["url"])
        case ActionTypes.PAGE_CLOSE:
            page.close()
            if len(browser_ctx.pages) > 0:
                page = browser_ctx.pages[-1]
            else:
                page = browser_ctx.new_page()

        case ActionTypes.SELECT_OPTION:
            if action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                execute_playwright_select_option(locator_code, page)
            else:
                raise NotImplementedError(
                    "No proper locator found for select option action"
                )
        case ActionTypes.CHECK:
            if action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                execute_playwright_check(locator_code, page)
            else:
                raise NotImplementedError(
                    "No proper locator found for select option action"
                )

        case _:
            raise ValueError(f"Unknown action type: {action_type}")

    page.wait_for_timeout(int(sleep_after_execution * 1000))
    num_tabs_now = len(browser_ctx.pages)
    # if a new tab is opened by clicking, switch to the new tab
    if num_tabs_now > num_tabs_before:
        page = browser_ctx.pages[-1]
        page.bring_to_front()

    return page



@beartype
async def aexecute_action(
    action: Action, page: APage, browser_ctx: ABrowserContext
) -> APage:
    """Execute the async action on the ChromeDriver."""
    action_type = action["action_type"]
    match action_type:
        case ActionTypes.NONE:
            pass
        case ActionTypes.SCROLL:
            direction = "up" if "up" in action["direction"] else "down"
            await aexecute_scroll(direction, page)
        case ActionTypes.KEY_PRESS:
            keys = action["key_comb"]
            await aexecute_key_press(keys, page)

        case ActionTypes.MOUSE_CLICK:
            await aexecute_mouse_click(
                action["coords"][0], action["coords"][1], page
            )
        case ActionTypes.CLEAR:
            element_id = action["element_id"]
            element_center = obseration_processor.get_element_center(element_id)  # type: ignore[attr-defined]
            await execute_mouse_click(element_center[0], element_center[1], page)
            await execute_key_press("Meta+A", page)
            await execute_key_press('Backspace', page)
        case ActionTypes.MOUSE_HOVER:
            await aexecute_mouse_hover(
                action["coords"][0], action["coords"][1], page
            )
        case ActionTypes.KEYBOARD_TYPE:
            await aexecute_type(action["text"], page)

        case ActionTypes.CLICK:
            # check each kind of locator in order
            # TODO[shuyanzh]: order is temp now
            if action["element_id"]:
                raise NotImplementedError
            elif action["element_role"] and action["element_name"]:
                element_role = int(action["element_role"])
                element_name = action["element_name"]
                nth = action["nth"]
                await aexecute_focus(element_role, element_name, nth, page)
                await aexecute_click_current(page)
            elif action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                # [shuyanzh], don't support action args and kwargs now
                await aexecute_playwright_click(
                    locator_code=locator_code, page=page
                )
            else:
                raise ValueError("No proper locator found for click action")
        case ActionTypes.HOVER:
            if action["element_id"]:
                raise NotImplementedError
            elif action["element_role"] and action["element_name"]:
                element_role = int(action["element_role"])
                element_name = action["element_name"]
                nth = action["nth"]
                await aexecute_focus(element_role, element_name, nth, page)
            elif action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                # [shuyanzh], don't support action args and kwargs now
                await aexecute_playwright_hover(
                    locator_code=locator_code, page=page
                )
            else:
                raise NotImplementedError(
                    "No proper locator found for hover action"
                )
        case ActionTypes.TYPE:
            if action["element_id"]:
                raise NotImplementedError
            elif action["element_role"] and action["element_name"]:
                element_role = int(action["element_role"])
                element_name = action["element_name"]
                nth = action["nth"]
                await aexecute_focus(element_role, element_name, nth, page)
                await aexecute_type(action["text"], page)
                page.keyboard.press("Enter")
            elif action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                text = parsed_code[-1]["arguments"][0]
                # [shuyanzh], don't support action args and kwargs now
                await aexecute_playwright_type(
                    text=text, locator_code=locator_code, page=page
                )
                page.keyboard.press("Enter")
            else:
                raise NotImplementedError(
                    "No proper locator found for type action"
                )

        case ActionTypes.PAGE_FOCUS:
            page = browser_ctx.pages[action["page_number"]]
            await page.bring_to_front()
        case ActionTypes.NEW_TAB:
            page = await browser_ctx.new_page()
        case ActionTypes.GO_BACK:
            await page.go_back()
        case ActionTypes.GO_FORWARD:
            await page.go_forward()
        case ActionTypes.GOTO_URL:
            await page.goto(action["url"])
        case ActionTypes.PAGE_CLOSE:
            await page.close()
            if len(browser_ctx.pages) > 0:
                page = browser_ctx.pages[-1]
            else:
                page = await browser_ctx.new_page()

        case ActionTypes.SELECT_OPTION:
            if action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                await aexecute_playwright_select_option(locator_code, page)
            else:
                raise NotImplementedError(
                    "No proper locator found for select option action"
                )
        case ActionTypes.CHECK:
            if action["pw_code"]:
                parsed_code = parse_playwright_code(action["pw_code"])
                locator_code = parsed_code[:-1]
                await aexecute_playwright_check(locator_code, page)
            else:
                raise NotImplementedError(
                    "No proper locator found for select option action"
                )

        case _:
            raise ValueError(f"Unknown action type: {action_type}")

    return page


@beartype
def parse_playwright_code(code: str) -> list[ParsedPlaywrightCode]:
    # extract function calls
    if not code.startswith("page."):
        raise ValueError(
            f'Playwright action must start with "page.", but got {code}'
        )

    regex = r"\.(?![^\(\)]*\))"
    chain = re.split(regex, code)[1:]

    parsed_chain = []

    for item in chain:
        tree = ast.parse(item)
        funcs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function_name = node.func.id  # type: ignore[attr-defined]
                arguments = [
                    ast.literal_eval(arg) if isinstance(arg, ast.Str) else arg
                    for arg in node.args
                ]
                keywords = {
                    str(kw.arg): ast.literal_eval(kw.value)
                    for kw in node.keywords
                }
                funcs.append(
                    ParsedPlaywrightCode(
                        {
                            "function_name": function_name,
                            "arguments": arguments,
                            "keywords": keywords,
                        }
                    )
                )

        if len(funcs) != 1:
            raise ValueError(f"Fail to parse {item} in {code}")

        if (
            funcs[0]["function_name"]
            not in PLAYWRIGHT_LOCATORS + PLAYWRIGHT_ACTIONS
        ):
            raise ValueError(
                f"Invalid playwright code {item}, ",
                f"the function needs to be one of {PLAYWRIGHT_LOCATORS + PLAYWRIGHT_ACTIONS}",
            )

        parsed_chain.append(funcs[0])

    last_action = parsed_chain[-1]
    if last_action["function_name"] not in PLAYWRIGHT_ACTIONS:
        raise ValueError(
            f"Invalid playwright action {last_action},",
            f"the action needs to be one of {PLAYWRIGHT_ACTIONS}",
        )

    return parsed_chain


@beartype
class ActionParsingError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


@beartype
def create_playwright_action(playwright_code: str) -> Action:
    """Main function to return individual playwright action"""
    # get the last action
    regex = r"\.(?![^\(\)]*\))"
    action = re.split(regex, playwright_code)[-1].split("(")[0]
    match action:
        case "press":
            p = r'press\((?:"|\')(.+?)(?:"|\')\)'
            match = re.search(p, playwright_code)
            if not match:
                raise ActionParsingError(
                    f"Invalid press action, required to be page.press(KEY_COMB_STR)"
                )
            key_comb = match.group(1)
            return create_key_press_action(key_comb=key_comb)
        case "scroll":
            direction = "up" if "up" in playwright_code else "down"
            return create_scroll_action(direction=direction)
        case "click":
            return create_click_action(pw_code=playwright_code)
        case "clear":
            return create_clear_action(pw_code=playwright_code)
        case "hover":
            return create_hover_action(pw_code=playwright_code)
        case "type" | "fill":
            p = r'type|fill\((?:"|\')(.+?)(?:"|\')\)'
            match = re.search(p, playwright_code)
            if not match:
                raise ActionParsingError(
                    f"Invalid type/fill action, required to be page.type(TEXT)"
                )
            text = match.group(1)
            return create_type_action(text=text, pw_code=playwright_code)
        case "select_option":
            return create_select_option_action(pw_code=playwright_code)
        case "check":
            return create_check_action(pw_code=playwright_code)
        case "goto":
            p = r'goto\((?:"|\')(.+?)(?:"|\')\)'
            match = re.search(p, playwright_code)
            if not match:
                raise ActionParsingError(
                    f"Invalid goto action, required to be page.goto(URL_STR)"
                )
            url = match.group(1)
            return create_goto_url_action(url)
        case "page_focus":
            # get the page number
            p = r"page_focus\((\d+)\)"
            match = re.search(p, playwright_code)
            if not match:
                raise ActionParsingError("page focus requires a page number")
            page_num = int(match.group(1))
            return create_page_focus_action(page_num)
        case "new_tab":
            return create_new_tab_action()
        case "go_back":
            return create_go_back_action()
        case "go_forward":
            return create_go_forward_action()
        case "page_close":
            return create_page_close_action()
        case "stop":  # page.stop(answer)
            p = r'stop\(?"(.+)?"\)'
            match = re.search(p, playwright_code)
            if not match:
                answer = ""
            else:
                answer = match.group(1)
            return create_stop_action(answer)

    raise ActionParsingError(f"Unknown playwright action {action}")


@beartype
def create_id_based_action(action_str: str) -> Action:
    # parsing
    try:
        match = re.search(r"(\w+)\s*\[([^\]]+)\]\s*\[([^\]]*)\]", action_str)
        if match:
            action_type, element_id, text = match.groups()
            action_type = action_type.upper()
            if action_type == "TYPE":
                action = create_type_action(
                    element_id=element_id,
                    text=text,
                )
                action["action_type"] = ActionTypes.TYPE
                return action
            else:
                raise ActionParsingError(f"Invalid action type: {action_type}")

        match = re.search(r"(\w+)\s*\[([^\]]+)\]", action_str)
        if match:
            action_type, arg = match.groups()
            action_type = action_type.upper()
            if action_type == "CLICK":
                action = create_click_action(element_id=arg)
                action["action_type"] = ActionTypes.CLICK
                return action
            elif action_type == "HOVER":
                action = create_hover_action(element_id=arg)
                action["action_type"] = ActionTypes.HOVER
                return action
            elif action_type == "CLEAR":
                action = create_clear_action(element_id=arg)
                action["action_type"] = ActionTypes.CLEAR
                return action
            elif action_type == "SCROLL":
                return create_scroll_action(direction=arg)
            elif action_type == "PRESS":
                return create_key_press_action(key_comb=arg)
            elif action_type == "GOTO":
                return create_goto_url_action(url=arg)
            elif action_type == "PAGE_FOCUS":
                return create_page_focus_action(page_number=int(arg))
            elif action_type == "STOP":
                return create_stop_action(answer=arg)

        # parameter-less actions
        if "new_tab" in action_str:
            return create_new_tab_action()
        elif "close_tab" in action_str:
            return create_page_close_action()
        elif "go_back" in action_str:
            return create_go_back_action()
        elif "go_forward" in action_str:
            return create_go_forward_action()

        return create_none_action()

    except Exception as e:
        return create_none_action()


@beartype
def create_webrl_id_based_action(action_str: str) -> Action:
    """Parse a webrl_id-based action string and return the corresponding action."""
    
    print(f"DEBUG: Raw action_str input: '{action_str}'")
    
    def remove_comments(code):
        # remove comments from the code
        code = re.sub(r"#[^\n]*", "", code)
        return code

    def parse_function_call(expression: str) -> dict[str, Any]:
        """Parse a function call expression."""
        expression = expression.strip()
        print(f"DEBUG: Parsing expression: '{expression}'")
        
        # Extract function name and arguments
        match = re.match(r'(\w+)\s*\((.*)\)', expression)
        if not match:
            raise ValueError("Not a valid function call format")
        
        func_name = match.group(1)
        args_str = match.group(2)
        
        print(f"DEBUG: Function name: '{func_name}', args string: '{args_str}'")
        
        # Parse arguments using regex
        args = {}
        # Pattern to match key=value pairs, handling both quoted and unquoted values
        arg_pattern = r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,\)]+))'
        
        for match in re.finditer(arg_pattern, args_str):
            key = match.group(1)
            # Get the value from whichever group matched (quoted with ", quoted with ', or unquoted)
            value = match.group(2) or match.group(3) or match.group(4).strip()
            
            # Handle bid -> element_id conversion
            if key == 'bid':
                key = 'element_id'
            
            # Try to convert to appropriate type
            if value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False
            elif value.isdigit():
                value = int(value)
            
            args[key] = value
        
        print(f"DEBUG: Parsed args: {args}")
        return {"function": func_name, "args": args}

    # Remove comments and clean up the action string
    action_str = remove_comments(action_str)
    print(f"DEBUG: After removing comments: '{action_str}'")
    
    # Extract function calls using regex
    pattern = r'(\w+)\s*\([^)]*\)'
    matches = re.findall(pattern, action_str)
    print(f"DEBUG: Regex matches: {matches}")
    
    # Find the actual function call in the string
    function_pattern = r'(type|click|scroll|key|wait|select_option|go_back)\s*\([^)]*\)'
    function_match = re.search(function_pattern, action_str, re.IGNORECASE)
    
    if not function_match:
        print("DEBUG: No function match found, returning NONE action")
        return create_none_action()
    
    function_call = function_match.group(0)
    print(f"DEBUG: Found function call: '{function_call}'")
    
    try:
        parsed = parse_function_call(function_call)
        func_name = parsed["function"].lower()
        args = parsed["args"]
        
        print(f"DEBUG: Final parsed function: '{func_name}', args: {args}")
        
        if func_name == "type":
            element_id = str(args.get("element_id", args.get("bid", "")))
            text = str(args.get("value", ""))
            return create_type_action(element_id=element_id, text=text)
        elif func_name == "click":
            element_id = str(args.get("element_id", args.get("bid", "")))
            return create_click_action(element_id=element_id)
        elif func_name == "select_option":
            element_id = str(args.get("element_id", args.get("bid", "")))
            options = str(args.get("options", ""))
            return create_select_dropdown_option_action(element_id=element_id, argument=options)
        elif func_name == "go_back":
            return create_go_back_action()
        else:
            print(f"DEBUG: Unknown function '{func_name}', returning NONE")
            return create_none_action()
            
    except Exception as e:
        print(f"DEBUG: Exception during parsing: {e}")
        return create_none_action()

__all__ = [
    "Action",
    "ActionTypes",
    "create_none_action",
    "create_stop_action",
    "create_scroll_action",
    "create_mouse_hover_action",
    "create_key_press_action",
    "create_page_focus_action",
    "create_new_tab_action",
    "create_go_back_action",
    "create_go_forward_action",
    "create_goto_url_action",
    "create_page_close_action",
    "create_mouse_click_action",
    "create_clear_action",
    "create_keyboard_type_action",
    "create_click_action",
    "create_hover_action",
    "create_type_action",
    "create_type_action_webrl",
    "create_search_action",
    "create_select_dropdown_option_action",
    "create_check_action",
    "create_select_option_action",
    "create_focus_action",
    "create_focus_and_click_action",
    "create_focus_and_type_action",
    "execute_scroll",
    "execute_scroll_webrl",
    "aexecute_scroll",
    "execute_key_press",
    "aexecute_key_press",
    "execute_mouse_hover",
    "aexecute_mouse_hover",
    "execute_mouse_click",
    "aexecute_mouse_click",
    "execute_keyboard_type",
    "aexecute_keyboard_type",
    "execute_click_current",
    "aexecute_click_current",
    "execute_type",
    "aexecute_type",
    "execute_focus",
    "aexecute_focus",
    "locate",
    "alocate",
    "execute_playwright_click",
    "aexecute_playwright_click",
    "execute_playwright_hover",
    "aexecute_playwright_hover",
    "execute_playwright_type",
    "aexecute_playwright_type",
    "execute_playwright_select_option",
    "aexecute_playwright_select_option",
    "execute_playwright_check",
    "aexecute_playwright_check",
    "execute_action_webrl",
    "execute_action",
    "aexecute_action",
    "parse_playwright_code",
    "create_playwright_action",
    "create_id_based_action",
    "create_webrl_id_based_action",
]