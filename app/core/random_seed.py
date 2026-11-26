"""可复现随机布局：统一的种子控件与随机数生成器。"""

from __future__ import annotations

import numpy as np
import streamlit as st


def seed_control(key: str, label: str = "随机种子", default: int = 42) -> int:
    st.number_input(
        label,
        min_value=0,
        max_value=2_147_483_647,
        value=default,
        step=1,
        key=key,
        help="相同数据、参数和种子会生成相同随机布局，并随项目包保存。",
    )
    return int(st.session_state.get(key, default))


def rng_for(key: str, default: int = 42) -> np.random.Generator:
    raw = st.session_state.get(key, default)
    try:
        seed = int(raw)
    except (TypeError, ValueError):
        seed = default
    return np.random.default_rng(max(0, min(seed, 2_147_483_647)))
