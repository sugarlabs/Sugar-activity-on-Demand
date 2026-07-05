# Copyright (C) 2026 Sugar Labs
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Studio-wide GTK stylesheet for the create/studio panel."""

from sugar3.graphics import style

_CSS_TEMPLATE = '''
            .create-ai-panel {
                background-color: %(studio_canvas)s;
            }
            .create-ai-title {
                color: %(black)s;
            }
            .create-ai-subtitle {
                color: %(inactive_stroke)s;
            }
            .create-ai-overlay-button {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                padding: 2px;
                min-width: 0;
                min-height: 0;
            }
            .create-ai-overlay-button:hover {
                background-color: %(studio_lavender_soft)s;
            }
            .create-ai-stage-card {
                background-color: %(studio_surface)s;
                border: 1px solid %(studio_edge)s;
                border-radius: 12px;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.10);
            }
            .create-ai-stage-card-hover {
                background-color: %(studio_lavender_soft)s;
                border: 1px solid %(studio_lavender_border)s;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.14);
            }
            .create-ai-stage-card-hover label {
                color: %(toolbar)s;
            }
            .create-ai-home-empty {
                padding: 30px;
            }
            .create-ai-stage-title {
                color: %(toolbar)s;
                font-weight: 700;
            }
            .create-ai-stage-details {
                color: %(toolbar)s;
            }
            .create-ai-stage-footer {
                color: %(black)s;
                font-weight: 700;
            }
            .create-ai-builder-title {
                color: #202020;
                font-weight: 700;
                font-size: 24px;
            }
            .create-ai-builder-subtitle {
                color: #686868;
                font-size: 13px;
            }
            .create-ai-hero-title {
                color: #1c1c1c;
                font-weight: 700;
                font-size: 30px;
            }
            .create-ai-template-caption {
                color: #8a8a8a;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.04em;
            }
            button.create-ai-prompt-chip {
                border-radius: 10px;
                border: 1px solid #e3e3e3;
                background-image: none;
                background-color: #fafafa;
                padding: 3px 10px;
                min-height: 0;
            }
            button.create-ai-prompt-chip label {
                color: #333333;
            }
            button.create-ai-prompt-chip:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_faint)s;
            }
            button.create-ai-prompt-chip-active {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
            }
            .create-ai-chip-caption {
                color: #9a9a9a;
                font-size: 9px;
            }
            .create-ai-chip-value {
                color: %(toolbar)s;
                font-size: 11px;
                font-weight: 700;
            }
            .create-ai-chip-caret {
                color: #9a9a9a;
                font-size: 8px;
            }
            .create-ai-prompt-status {
                color: #8a8a8a;
                font-size: 11px;
            }
            popover.create-ai-popover {
                background-color: %(studio_surface)s;
                border: 1px solid %(studio_edge)s;
                border-radius: 10px;
            }
            .create-ai-provider-heading {
                color: #202020;
                font-weight: 700;
                font-size: 13px;
            }
            .create-ai-provider-status {
                color: #7a7a7a;
                font-size: 10px;
            }
            button.create-ai-provider-primary {
                border-radius: 7px;
                border: 1px solid %(studio_dark)s;
                background-image: none;
                background-color: %(studio_dark)s;
                color: %(studio_dark_text)s;
                padding: 7px 12px;
                font-size: 11px;
                font-weight: 700;
            }
            button.create-ai-provider-primary label {
                color: %(studio_dark_text)s;
            }
            button.create-ai-provider-primary:hover {
                background-color: %(studio_dark_hover)s;
                border-color: %(studio_dark_hover)s;
            }
            button.create-ai-template-card {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 0;
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
                transition: background-color 120ms ease,
                            border-color 120ms ease,
                            box-shadow 120ms ease;
            }
            button.create-ai-template-card:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_faint)s;
                box-shadow: 0 4px 9px rgba(0, 0, 0, 0.12);
            }
            .create-ai-meta-label {
                color: %(toolbar)s;
                font-weight: 700;
                font-size: 12px;
            }
            .create-ai-meta-note {
                color: #747474;
                font-size: 11px;
            }
            progressbar.create-ai-generation-progress trough {
                min-height: 6px;
                border-radius: 999px;
                border: 0;
                background-color: #ececec;
            }
            progressbar.create-ai-generation-progress progress {
                min-height: 6px;
                border-radius: 999px;
                background-color: %(studio_lavender_border)s;
            }
            .create-ai-generation-stage {
                color: #888;
                font-weight: 400;
                font-size: 11px;
            }
            .create-ai-generation-fun {
                color: #a58324;
                font-size: 11px;
                font-style: italic;
            }
            .create-ai-generation-step {
                color: #aaa;
                font-size: 11px;
                font-weight: 400;
                transition: color 250ms ease-out;
            }
            .create-ai-generation-step-active {
                color: #333;
                font-weight: 600;
            }
            .create-ai-generation-step-desc {
                color: #b8b8b8;
                font-size: 9px;
            }
            .create-ai-generation-step-row {
                padding: 6px 10px;
                border-radius: 8px;
                border: 1px solid transparent;
                transition: background-color 250ms ease-out,
                            border-color 250ms ease-out;
            }
            .create-ai-generation-step-row-active {
                background-color: %(studio_lavender_soft)s;
                border: 1px solid %(studio_lavender_border)s;
            }
            .create-ai-generated-preview {
                border-radius: 8px;
                border: 0;
                background-color: transparent;
                box-shadow: none;
            }
            .create-ai-generated-title {
                color: #202020;
                font-weight: 700;
                font-size: 17px;
            }
            .create-ai-generated-badge {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_lavender_soft)s;
                color: #555555;
                padding: 2px 9px;
                font-size: 10px;
            }
            .create-ai-generated-summary {
                color: #696969;
                font-size: 11px;
            }
            .create-ai-generated-body {
                border-radius: 8px;
                border: 1px solid %(studio_edge_soft)s;
                background-color: %(studio_preview)s;
                padding: 12px;
            }
            .create-ai-generated-kicker {
                color: #6f6f6f;
                font-size: 10px;
                font-weight: 700;
            }
            .create-ai-generated-question {
                color: #202020;
                font-size: 14px;
                font-weight: 700;
            }
            entry.create-ai-generated-entry {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                padding: 7px 9px;
                font-size: 11px;
            }
            button.create-ai-generated-action {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            button.create-ai-generated-tile {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                font-weight: 700;
            }
            button.create-ai-generated-tile:checked {
                background-color: %(studio_cream)s;
                border-color: %(studio_cream_border)s;
            }
            .create-ai-generated-canvas {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
            }
            .create-ai-generated-log {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
            }
            button.create-ai-generated-chess-square {
                border-radius: 2px;
                border: 0;
                background-image: none;
                background-color: #eeeeee;
                color: #202020;
                font-weight: 700;
                font-size: 20px;
                padding: 0;
            }
            button.create-ai-generated-chess-dark {
                background-color: #cfcfcf;
            }
            button.create-ai-generated-chess-selected {
                background-color: #f4d06f;
            }
            .create-ai-generated-pill {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_lavender_soft)s;
                color: #5f5f5f;
                padding: 2px 8px;
                font-size: 10px;
            }
            .create-ai-pill-button {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 1px 10px;
                min-height: 0;
                font-size: 11px;
            }
            .create-ai-pill-button:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_faint)s;
            }
            .create-ai-pill-active {
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                border-color: %(studio_lavender_border)s;
            }
            .create-ai-pill-active label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-meta-button {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 2px 12px;
                font-size: 11px;
            }
            .create-ai-meta-button:checked {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
            }
            combobox.create-ai-provider-combo button {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 7px 10px;
                font-size: 11px;
            }
            entry.create-ai-provider-entry {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                color: %(black)s;
                padding: 8px 10px;
                font-size: 11px;
            }
            button.create-ai-provider-button {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 7px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            button.create-ai-provider-button:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
            }
            .create-ai-section-label {
                color: %(inactive_stroke)s;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 0.06em;
            }
            .create-ai-expander {
                color: %(toolbar)s;
                font-size: 12px;
            }
            .create-ai-option-heading {
                color: %(toolbar)s;
                font-weight: 700;
                font-size: 12px;
            }
            button.create-ai-option-card {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 0;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
                transition: background-color 120ms ease,
                            border-color 120ms ease,
                            box-shadow 120ms ease;
            }
            button.create-ai-option-card:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_faint)s;
                box-shadow: 0 2px 5px rgba(0, 0, 0, 0.09);
            }
            button.create-ai-option-card-active {
                background-color: %(studio_dark)s;
                border-color: %(studio_dark)s;
                color: %(studio_dark_text)s;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.18);
            }
            button.create-ai-option-card-active:hover {
                background-color: %(studio_dark_hover)s;
                border-color: %(studio_dark_hover)s;
            }
            button.create-ai-option-card-active:hover label {
                color: %(studio_dark_text)s;
            }
            .create-ai-option-title {
                color: %(toolbar)s;
                font-weight: 700;
                font-size: 12px;
            }
            .create-ai-option-detail {
                color: %(inactive_stroke)s;
                font-size: 10px;
            }
            button.create-ai-option-card-active label {
                color: %(studio_dark_text)s;
            }
            .create-ai-prompt-box {
                border-radius: 14px;
                border: 1px solid #e2e2e2;
                background-color: %(studio_surface)s;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06),
                            0 1px 2px rgba(0, 0, 0, 0.04);
            }
            .create-ai-prompt-box-focused {
                border-color: #b8b8b8;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.09),
                            0 1px 3px rgba(0, 0, 0, 0.05);
            }
            textview.create-ai-textview {
                color: %(black)s;
                background-color: transparent;
                border: 0;
                border-radius: 0;
                font-size: 13px;
            }
            textview.create-ai-textview text {
                color: %(black)s;
                background-color: transparent;
            }
            textview.create-ai-textview:focus {
                border: 0;
                box-shadow: none;
                background-color: transparent;
            }
            .create-ai-prompt-divider {
                background-color: #ebebeb;
                min-height: 1px;
            }
            .create-ai-prompt-actions {
                border-radius: 0 0 13px 13px;
                border: 0;
                background-color: transparent;
            }
            .create-ai-plus {
                border-radius: 999px;
                border: 1px solid #d4d4d4;
                background-image: none;
                background-color: #f5f5f5;
                color: %(studio_lavender_text)s;
                padding: 0 4px;
                min-width: 28px;
                min-height: 28px;
            }
            .create-ai-plus:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
            }
            .create-ai-plus label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-send {
                border-radius: 999px;
                border: 1px solid %(toolbar)s;
                background-image: none;
                background-color: %(toolbar)s;
                color: %(white)s;
                padding: 0;
                min-width: 34px;
                min-height: 34px;
            }
            .create-ai-send label {
                color: %(white)s;
            }
            .create-ai-send:hover {
                background-color: %(black)s;
                border-color: %(black)s;
            }
            .create-ai-studio-workspace {
                border-radius: 14px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_canvas)s;
            }
            .create-ai-studio-side {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.07);
            }
            .create-ai-studio-chip {
                border-radius: 12px;
                border: 1px solid %(studio_lavender_border)s;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 8px 16px;
                font-weight: 700;
            }
            .create-ai-studio-chip label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-studio-note {
                border-radius: 10px;
                border: 1px solid %(studio_cream_border)s;
                background-color: %(studio_cream)s;
            }
            .create-ai-studio-note-label {
                color: %(toolbar)s;
                font-size: 11px;
            }
            .create-ai-chat-scroll {
                border: 0;
                background-color: transparent;
            }
            .create-ai-chat-heading {
                color: %(toolbar)s;
                font-weight: 700;
                font-size: 12px;
            }
            .create-ai-chat-bubble {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
            }
            .create-ai-chat-bubble-ai {
                background-color: %(studio_cream)s;
                border-color: %(studio_cream_border)s;
            }
            .create-ai-chat-bubble-user {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
            }
            .create-ai-chat-bubble-user label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-chat-text {
                color: %(toolbar)s;
                font-size: 12px;
            }
            .create-ai-chat-status {
                color: #5f5f5f;
                font-size: 11px;
                padding: 2px 4px;
            }
            .create-ai-chat-composer {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.07);
            }
            entry.create-ai-chat-entry {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 9px;
                font-size: 12px;
            }
            button.create-ai-chat-send {
                border-radius: 7px;
                border: 1px solid %(studio_lavender_border)s;
                background-image: none;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 700;
            }
            button.create-ai-chat-send:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
            }
            button.create-ai-chat-send label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-studio-mini-prompt {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
            }
            entry.create-ai-studio-entry {
                border-radius: 6px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                color: %(inactive_stroke)s;
                font-size: 11px;
            }
            .create-ai-studio-section-title {
                color: %(toolbar)s;
                font-weight: 700;
                font-size: 12px;
            }
            button.create-ai-studio-button {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 5px 13px;
                font-size: 11px;
            }
            button.create-ai-studio-button:hover {
                background-color: %(studio_preview)s;
                border-color: %(studio_edge)s;
            }
            button.create-ai-studio-primary {
                border-radius: 999px;
                border: 1px solid %(studio_lavender_border)s;
                background-image: none;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 5px 13px;
                font-size: 11px;
                font-weight: 700;
            }
            button.create-ai-studio-primary label {
                color: %(studio_lavender_text)s;
            }
            button.create-ai-studio-tab {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 7px 16px;
                font-weight: 700;
                font-size: 11px;
            }
            button.create-ai-studio-tab:hover {
                background-color: %(studio_preview)s;
                border-color: %(studio_edge)s;
            }
            button.create-ai-studio-tab-active {
                background-color: %(studio_dark)s;
                border-color: %(studio_dark)s;
                color: %(studio_dark_text)s;
                box-shadow: 0 2px 3px rgba(0, 0, 0, 0.16);
            }
            button.create-ai-studio-tab-active:hover {
                background-color: %(studio_dark_hover)s;
                border-color: %(studio_dark_hover)s;
                color: %(studio_dark_text)s;
            }
            button.create-ai-studio-tab-active label {
                color: %(studio_dark_text)s;
            }
            button.create-ai-studio-tab-active:hover label {
                color: %(studio_dark_text)s;
            }
            .create-ai-soft-pill {
                border-radius: 999px;
                border: 1px solid %(studio_lavender_border)s;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 3px 9px;
                font-size: 10px;
                font-weight: 700;
            }
            .create-ai-soft-pill:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
            }
            .create-ai-preview-shell {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
            }
            .create-ai-preview-frame {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_preview)s;
                box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.75);
            }
            .create-ai-activity-preview {
                background-color: transparent;
            }
            .create-ai-preview-title {
                color: %(toolbar)s;
                font-size: 18px;
                font-weight: 700;
            }
            .create-ai-review-shell {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
            }
            .create-ai-review-files {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_canvas)s;
            }
            button.create-ai-review-file {
                border-radius: 6px;
                border: 1px solid transparent;
                background-image: none;
                background-color: transparent;
                color: %(toolbar)s;
                padding: 7px 9px;
                font-size: 12px;
                text-shadow: none;
            }
            button.create-ai-review-file:hover {
                background-color: %(studio_preview)s;
                border-color: %(studio_edge)s;
            }
            button.create-ai-review-file-active {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
                font-weight: 700;
            }
            button.create-ai-review-file-active:hover {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
            }
            button.create-ai-review-file-active label {
                color: %(studio_lavender_text)s;
            }
            button.create-ai-review-file-active:hover label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-review-code {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
            }
            .create-ai-review-title {
                color: %(toolbar)s;
                font-size: 16px;
                font-weight: 700;
            }
            .create-ai-review-summary {
                color: %(toolbar)s;
                font-size: 12px;
            }
            .create-ai-review-meta {
                color: %(inactive_stroke)s;
                font-size: 11px;
                font-weight: 700;
            }
            .create-ai-code-frame {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
            }
            .create-ai-code-text {
                color: %(black)s;
                font-family: monospace;
                font-size: 13px;
            }
            .create-ai-versions-shell {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
            }
            .create-ai-version-history {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_canvas)s;
            }
            .create-ai-version-heading {
                color: %(toolbar)s;
                font-size: 11px;
                font-weight: 700;
            }
            .create-ai-version-card {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
            }
            .create-ai-version-card-active {
                border-color: %(studio_lavender_border)s;
                background-color: %(studio_lavender_soft)s;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
            }
            .create-ai-version-chip {
                border-radius: 999px;
                border: 1px solid %(studio_lavender_border)s;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 3px 8px;
                font-size: 10px;
                font-weight: 700;
            }
            .create-ai-version-date {
                color: %(inactive_stroke)s;
                font-size: 9px;
                font-weight: 700;
            }
            .create-ai-version-card-action {
                border-radius: 7px;
                border: 1px solid %(studio_lavender_border)s;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 5px 10px;
                font-size: 10px;
                font-weight: 700;
            }
            .create-ai-version-card-action label {
                color: %(studio_lavender_text)s;
            }
            button.create-ai-version-switch {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 7px 18px;
                font-weight: 700;
                font-size: 11px;
            }
            button.create-ai-version-switch:hover {
                background-color: %(studio_preview)s;
                border-color: %(studio_edge)s;
            }
            button.create-ai-version-switch-active {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
                box-shadow: 0 2px 3px rgba(0, 0, 0, 0.09);
            }
            button.create-ai-version-switch-active:hover {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
            }
            button.create-ai-version-switch-active label {
                color: %(studio_lavender_text)s;
            }
            button.create-ai-version-switch-active:hover label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-version-compare-pill {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 4px 12px;
                font-size: 10px;
                font-weight: 700;
            }
            .create-ai-live-edit-panel {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.07);
            }
            .create-ai-live-toggle-group {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_canvas)s;
            }
            button.create-ai-live-toggle {
                border-radius: 999px;
                border: 1px solid transparent;
                background-image: none;
                background-color: transparent;
                color: %(inactive_stroke)s;
                padding: 3px 12px;
                font-size: 10px;
                font-weight: 700;
                min-height: 0;
            }
            button.create-ai-live-toggle:hover {
                background-color: %(studio_lavender_soft)s;
            }
            button.create-ai-live-toggle-active {
                background-color: %(studio_cream)s;
                border-color: %(studio_cream_border)s;
                color: %(studio_cream_text)s;
            }
            button.create-ai-live-toggle-active label {
                color: %(studio_cream_text)s;
            }
            .create-ai-live-target {
                border-radius: 7px;
                border: 1px solid %(studio_lavender_border)s;
                background-color: %(studio_lavender_soft)s;
                color: %(toolbar)s;
                padding: 11px 12px;
                font-size: 11px;
            }
            entry.create-ai-live-entry {
                border-radius: 7px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                color: %(black)s;
                padding: 12px;
                font-size: 12px;
            }
            button.create-ai-preview-change {
                border-radius: 8px;
                border: 1px solid %(studio_lavender_border)s;
                background-image: none;
                background-color: %(studio_lavender)s;
                color: %(studio_lavender_text)s;
                padding: 12px 18px;
                font-size: 12px;
                font-weight: 700;
            }
            button.create-ai-preview-change:hover {
                background-color: %(studio_lavender_soft)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
            }
            button.create-ai-preview-change label {
                color: %(studio_lavender_text)s;
            }
            .live-edit-selected {
                border: 2px solid rgba(255, 200, 0, 0.85);
                border-radius: 3px;
            }
            .create-ai-ask-bar {
                border-radius: 999px;
                border: 1px solid #3d3d3d;
                background-color: #2b2b2b;
                box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
            }
            .create-ai-ask-mode-group {
                border-radius: 999px;
                border: 1px solid #4d4d4d;
                background-color: #232323;
            }
            button.create-ai-ask-mode {
                border-radius: 999px;
                border: 1px solid transparent;
                background-image: none;
                background-color: transparent;
                padding: 2px 10px;
                font-size: 10px;
                font-weight: 700;
                min-height: 0;
            }
            button.create-ai-ask-mode label {
                color: #b8b8b8;
            }
            button.create-ai-ask-mode:hover {
                background-color: #3d3d3d;
            }
            button.create-ai-ask-mode-active {
                background-color: %(studio_cream)s;
                border-color: %(studio_cream_border)s;
            }
            button.create-ai-ask-mode-active label {
                color: %(studio_cream_text)s;
            }
            button.create-ai-ask-mode-active:hover {
                background-color: %(studio_cream)s;
            }
            button.create-ai-ask-plus {
                border-radius: 999px;
                border: 0;
                background-image: none;
                background-color: transparent;
                padding: 0;
                min-width: 30px;
                min-height: 30px;
            }
            button.create-ai-ask-plus:hover {
                background-color: #3d3d3d;
            }
            .create-ai-ask-target {
                border-radius: 999px;
                background-color: #3d3d3d;
                color: #d8d8d8;
                padding: 2px 10px;
                font-size: 10px;
            }
            entry.create-ai-ask-entry {
                border: 0;
                border-radius: 0;
                background-color: transparent;
                background-image: none;
                box-shadow: none;
                color: #f0f0f0;
                caret-color: #ffffff;
                font-size: 13px;
            }
            entry.create-ai-ask-entry:focus {
                border: 0;
                box-shadow: none;
            }
            .create-ai-ask-status {
                color: #9a9a9a;
                font-size: 10px;
            }
            button.create-ai-ask-send {
                border-radius: 999px;
                border: 1px solid #4d4d4d;
                background-image: none;
                background-color: #454545;
                padding: 0;
                min-width: 32px;
                min-height: 32px;
            }
            button.create-ai-ask-send:hover {
                background-color: #5a5a5a;
            }
            .create-ai-learning-sidebar {
                border-radius: 12px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
            }
            .create-ai-learning-card {
                border-radius: 10px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
            }
            .create-ai-learning-counts {
                border-radius: 999px;
                border: 1px solid %(studio_edge)s;
                background-color: %(studio_surface)s;
                color: %(inactive_stroke)s;
                padding: 3px 9px;
                font-size: 9px;
                font-weight: 700;
            }
            button.create-ai-sidebar-tab {
                border-radius: 8px;
                border: 1px solid %(studio_edge)s;
                background-image: none;
                background-color: %(studio_surface)s;
                color: %(toolbar)s;
                padding: 7px 12px;
                font-weight: 700;
                font-size: 11px;
            }
            button.create-ai-sidebar-tab:hover {
                background-color: %(studio_preview)s;
                border-color: %(studio_edge)s;
            }
            button.create-ai-sidebar-tab-active {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
                box-shadow: 0 2px 3px rgba(0, 0, 0, 0.09);
            }
            button.create-ai-sidebar-tab-active:hover {
                background-color: %(studio_lavender)s;
                border-color: %(studio_lavender_border)s;
                color: %(studio_lavender_text)s;
            }
            button.create-ai-sidebar-tab-active label {
                color: %(studio_lavender_text)s;
            }
            button.create-ai-sidebar-tab-active:hover label {
                color: %(studio_lavender_text)s;
            }
            .create-ai-challenge-card {
                border-radius: 10px;
                border: 1px solid %(studio_edge_soft)s;
                background-color: %(studio_surface)s;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
            }
        '''


def _colors():
    return {
        'black': style.COLOR_BLACK.get_html(),
        'button': style.COLOR_BUTTON_GREY.get_html(),
        'highlight': style.COLOR_HIGHLIGHT.get_html(),
        'inactive_fill': style.COLOR_INACTIVE_FILL.get_html(),
        'inactive_stroke': style.COLOR_INACTIVE_STROKE.get_html(),
        'panel': style.COLOR_PANEL_GREY.get_html(),
        'selection': style.COLOR_SELECTION_GREY.get_html(),
        'text_field': style.COLOR_TEXT_FIELD_GREY.get_html(),
        'toolbar': style.COLOR_TOOLBAR_GREY.get_html(),
        'white': style.COLOR_WHITE.get_html(),
        'studio_canvas': '#f2f2f2',
        'studio_surface': '#ffffff',
        'studio_preview': '#fcfcfc',
        'studio_edge': '#cfcfcf',
        'studio_edge_soft': '#e7e7e7',
        'studio_dark': '#2f2f2f',
        'studio_dark_hover': '#414141',
        'studio_dark_text': '#ffffff',
        'studio_lavender': '#e9e9e9',
        'studio_lavender_soft': '#f7f7f7',
        'studio_lavender_faint': '#d8d8d8',
        'studio_lavender_border': '#9a9a9a',
        'studio_lavender_text': '#202020',
        'studio_cream': '#fff4d8',
        'studio_cream_border': '#ddbd73',
        'studio_cream_text': '#322717',
    }


def get_css():
    """Return the fully substituted studio stylesheet."""
    return _CSS_TEMPLATE % _colors()
