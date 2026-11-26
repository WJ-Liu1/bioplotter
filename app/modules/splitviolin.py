from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.stats import t as t_dist

from app.core.io_utils import read_table
from app.core.sample_utils import get_sample_path, sample_loader_control
from app.core.theme import THEMES

HELP_TEXT = """
Split Violin Plot (Plotly 交互版本)

Input data format:
  - At least 3 columns, in order: value, Group, Attribute
  - value: numeric column
  - Group: grouping column (x-axis)
  - Attribute: splitting attribute (defines left/right side of the violin)

Features:
  - Generates a split violin plot with mirrored density on both sides
  - Shows mean points with 95% confidence interval error bars
  - Supports custom colors (maximum two groups, automatic palette for more)
  - Supports title, axis labels, legend settings

Note:
  - This module uses pure Python for kernel density estimation and split-violin geometry
  - Help, data preview, download are handled by the main program
"""

def _load_current_df():
    use_sample = st.session_state.get("splitviolin_use_sample", True)
    uploaded = st.session_state.get("splitviolin_upload", None)

    if use_sample:
        try:
            sample_path = get_sample_path("splitviolin")
            if not sample_path.exists():
                return None, f"Sample data file does not exist: {sample_path}"
            df = read_table(sample_path, sample_path.name)
            if df is None or df.empty:
                return None, "Sample data is empty."
            return df, None
        except Exception as exc:
            return None, f"Failed to read sample data: {exc}"

    if uploaded is None:
        return None, "Please upload a data file first, or check 'Use sample data'."

    try:
        df = read_table(uploaded, uploaded.name)
        return df, None
    except Exception as exc:
        return None, f"Failed to read file: {exc}"

# ========== Kernel density estimation ==========
def _r_bw_nrd0(x):
    """nrd0 带宽选择"""
    x = np.asarray(x)
    n = len(x)
    if n == 0:
        return 0
    hi = np.std(x, ddof=1)
    iqr = np.percentile(x, 75) - np.percentile(x, 25)
    lo = min(hi, iqr / 1.34)
    if lo == 0:
        lo = hi
    if lo == 0:
        lo = np.abs(x).mean() or 1
    return 0.9 * lo * n ** (-0.2)

def _r_density(x, n=512, cut=3):
    """
    Gaussian kernel density with configurable grid size and cut.
    Returns (y_grid, density)
    """
    x = np.asarray(x)
    if len(x) < 2:
        return None, None
    bw = _r_bw_nrd0(x)
    if bw == 0:
        return None, None
    # Range: min(x) - cut*bw  to  max(x) + cut*bw
    xmin = x.min() - cut * bw
    xmax = x.max() + cut * bw
    y_grid = np.linspace(xmin, xmax, n)
    # Gaussian kernel density estimation (vectorized acceleration)
    # Formula: density = (1/(n*bw)) * sum(K((y - xi)/bw))
    # K(u) = (1/sqrt(2π)) * exp(-u^2/2)
    inv_n = 1.0 / len(x)
    inv_bw = 1.0 / bw
    sqrt_2pi = np.sqrt(2 * np.pi)
    density = np.zeros_like(y_grid)
    for xi in x:
        u = (y_grid - xi) * inv_bw
        density += np.exp(-0.5 * u * u) / sqrt_2pi
    density *= inv_n * inv_bw
    return y_grid, density

# ========== Split violin geometry calculation ==========
def _compute_violin_polygon(x_center, y_grid, density, max_width, side='left'):
    """
    Compute (x, y) points for one side of the violin polygon based on density curve
    side: 'left' or 'right'
    max_width: maximum violin width (0.9 times group spacing)
    """
    if density is None or len(density) == 0:
        return None, None
    # Normalize density to [0,1] and scale to max width
    if density.max() > 0:
        width = (density / density.max()) * max_width
    else:
        width = np.zeros_like(density)
    if side == 'left':
        x_coords = x_center - width
        # Left polygon sorted by ascending y
        order = np.argsort(y_grid)
        x_out = x_coords[order]
        y_out = y_grid[order]
    else:  # right
        x_coords = x_center + width
        # Right polygon sorted by descending y (to ensure correct closure direction)
        order = np.argsort(-y_grid)
        x_out = x_coords[order]
        y_out = y_grid[order]
    return x_out, y_out

# ========== Streamlit controls ==========
def controls(shared: dict) -> None:
    st.session_state["splitviolin_use_sample"] = True

    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    st.markdown("### Data Input")
    sample_loader_control("splitviolin_use_sample", "splitviolin", "splitviolin_load_sample_btn")
    if not st.session_state.get("splitviolin_use_sample", True):
        st.file_uploader(
            "Upload data file (txt/tsv/csv)",
            type=["txt", "tsv", "csv"],
            key="splitviolin_upload"
        )

    st.markdown("---")
    st.markdown("### Plot Settings")

    st.text_input("Plot title", value="title", key="splitviolin_title")
    st.slider("Title font size", 1, 150, 20, key="splitviolin_title_size")

    st.text_input("X-axis label", value="X title", key="splitviolin_x_title")
    st.text_input("Y-axis label", value="Y title", key="splitviolin_y_title")
    st.slider("Axis label font size", 1, 150, 20, key="splitviolin_axis_title_size")

    st.text_input("Legend title", value="legend", key="splitviolin_legend_title")
    st.slider("Legend title font size", 1, 150, 20, key="splitviolin_legend_size")

    st.color_picker("Panel background color", value="#BEBEBE", key="splitviolin_plot_bg")
    st.color_picker("Plot background color", value="#FFFFFF", key="splitviolin_paper_bg")

    st.color_picker("Attribute 1 color", value="#56B4E9", key="splitviolin_color1")
    st.color_picker("Attribute 2 color", value="#E69F00", key="splitviolin_color2")

    st.markdown("---")
    st.markdown("### Figure Size")
    st.number_input("Height (pixels)", value=750, min_value=200, step=50, key="splitviolin_height")
    st.number_input("Width (pixels)", value=750, min_value=200, step=50, key="splitviolin_width")

# ========== Main build function ==========
def build(shared: dict):
    current_theme = st.session_state.theme
    theme = THEMES[current_theme]

    df, err = _load_current_df()
    if err:
        return None, None, err, HELP_TEXT
    if df is None:
        return None, None, "No data available.", HELP_TEXT

    # Data format check
    if df.shape[1] < 3:
        return None, None, "Data must have at least 3 columns: 1st numeric, 2nd group, 3rd attribute", HELP_TEXT

    # Rename columns
    df.columns = ['value', 'Group', 'Attribute'] + list(df.columns[3:])
    df['Group'] = df['Group'].astype('category')
    df['Attribute'] = df['Attribute'].astype('category')

    attrs = df['Attribute'].cat.categories
    groups = df['Group'].cat.categories

    # Split violin plot requires exactly two attributes
    if len(attrs) != 2:
        st.error("Split Violin Plot requires exactly 2 distinct levels in the Attribute column.")
        return None, None, f"Current number of Attribute levels = {len(attrs)}, requires 2.", HELP_TEXT

    # Color mapping
    color1 = st.session_state.get("splitviolin_color1", "#56B4E9")
    color2 = st.session_state.get("splitviolin_color2", "#E69F00")
    color_map = {attrs[0]: color1, attrs[1]: color2}

    # Calculate means and 95% confidence intervals
    summary = df.groupby(['Group', 'Attribute'])['value'].agg(
        mean='mean', sem='sem', count='count'
    ).reset_index()
    summary['ci'] = summary.apply(
        lambda row: t_dist.ppf(0.975, row['count']-1) * row['sem'] if row['count'] > 1 else 0,
        axis=1
    )

    # Fixed parameters: group spacing = 1, maximum violin width = 0.9
    MAX_WIDTH = 0.9
    DODGE = 0.25          # offset for position_dodge(0.5)

    fig = go.Figure()

    # Generate left/right violins for each Group
    for i, group in enumerate(groups):
        x_center = i

        # Compute density curves for both attributes
        densities = []
        for attr in attrs:
            vals = df[(df['Group'] == group) & (df['Attribute'] == attr)]['value'].dropna()
            if len(vals) >= 2:
                y_grid, dens = _r_density(vals, n=512, cut=3)
                densities.append((y_grid, dens))
            else:
                densities.append((None, None))

        # Left side (first attribute)
        y_left, dens_left = densities[0]
        if y_left is not None:
            x_left, y_left_poly = _compute_violin_polygon(x_center, y_left, dens_left, MAX_WIDTH, side='left')
            if x_left is not None:
                fig.add_trace(go.Scatter(
                    x=x_left, y=y_left_poly,
                    mode='lines', fill='toself',
                    fillcolor=color_map[attrs[0]],
                    line=dict(color="#FFFFFF", width=1),
                    name=str(attrs[0]),
                    legendgroup=str(attrs[0]),
                    showlegend=(i == 0),
                    opacity=0.6,
                    hoverinfo='skip'
                ))

        # Right side (second attribute)
        y_right, dens_right = densities[1]
        if y_right is not None:
            x_right, y_right_poly = _compute_violin_polygon(x_center, y_right, dens_right, MAX_WIDTH, side='right')
            if x_right is not None:
                fig.add_trace(go.Scatter(
                    x=x_right, y=y_right_poly,
                    mode='lines', fill='toself',
                    fillcolor=color_map[attrs[1]],
                    line=dict(color="#FFFFFF", width=1),
                    name=str(attrs[1]),
                    legendgroup=str(attrs[1]),
                    showlegend=(i == 0),
                    opacity=0.6,
                    hoverinfo='skip'
                ))

        # Add mean points and error bars
        for j, attr in enumerate(attrs):
            row = summary[(summary['Group'] == group) & (summary['Attribute'] == attr)]
            if len(row) == 0:
                continue
            mean_val = row['mean'].iloc[0]
            ci_val = row['ci'].iloc[0]
            x_pos = x_center + (DODGE if j == 1 else -DODGE)
            line_color = "#000000"

            fig.add_trace(go.Scatter(
                x=[x_pos], y=[mean_val],
                mode='markers',
                marker=dict(color=line_color, size=3),
                showlegend=False,
                hoverinfo='y'
            ))
            # 误差棒 + 端帽（width = 0.05）
            fig.add_trace(go.Scatter(
                x=[x_pos, x_pos, None, x_pos - 0.025, x_pos + 0.025, None, x_pos - 0.025, x_pos + 0.025],
                y=[mean_val - ci_val, mean_val + ci_val, None, mean_val - ci_val, mean_val - ci_val, None, mean_val + ci_val, mean_val + ci_val],
                mode='lines',
                line=dict(color=line_color, width=1),
                opacity=0.5,
                showlegend=False,
                hoverinfo='none'
            ))

    # Layout settings
    plot_bg = st.session_state.get("splitviolin_plot_bg") or "#BEBEBE"
    paper_bg = st.session_state.get("splitviolin_paper_bg") or "#FFFFFF"
    title = st.session_state.get("splitviolin_title", "title")
    title_size = st.session_state.get("splitviolin_title_size", 20)
    x_title = st.session_state.get("splitviolin_x_title", "X title")
    y_title = st.session_state.get("splitviolin_y_title", "Y title")
    axis_title_size = st.session_state.get("splitviolin_axis_title_size", 20)
    legend_title = st.session_state.get("splitviolin_legend_title", "legend")
    legend_size = st.session_state.get("splitviolin_legend_size", 20)
    height = st.session_state.get("splitviolin_height", 750)
    width = st.session_state.get("splitviolin_width", 750)
    text_color = theme.get("text", "#000000")

    fig.update_layout(
        title=dict(text=title, font=dict(size=title_size, color=text_color), x=0.5),
        xaxis=dict(
            title=dict(text=x_title, font=dict(size=axis_title_size, color=text_color)),
            tickvals=list(range(len(groups))),
            ticktext=list(groups),
            tickfont=dict(color=text_color),
            range=[-0.5, len(groups) - 0.5]
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(size=axis_title_size, color=text_color)),
            tickfont=dict(color=text_color)
        ),
        legend=dict(
            title=dict(text=legend_title, font=dict(size=legend_size, color=text_color)),
            font=dict(color=text_color)
        ),
        plot_bgcolor=plot_bg,
        paper_bgcolor=paper_bg,
        width=width,
        height=height,
        showlegend=True
    )

    shared["last_plotly"] = fig
    shared["status"] = f"Split Violin plot generated, {len(df)} records total."
    shared["help_text"] = HELP_TEXT

    return fig, df, shared["status"], HELP_TEXT

def render(shared: dict):
    controls(shared)
    return build(shared)

__call__ = render