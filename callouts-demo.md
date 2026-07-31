---
excerpt: Every callout type wp-post can render, shown in the Ollie theme.
id: 2742
slug: callouts-demo
status: publish
title: Callout Demo
---

Each block below is written as an ordinary GFM blockquote in markdown and
rendered as core Gutenberg blocks, coloured from the theme palette rather
than from hardcoded values.

## The five GFM admonitions

> [!NOTE]
> Supporting detail that is worth setting apart from the body text.

> [!TIP]
> A shortcut that saves the reader time.

> [!IMPORTANT]
> Something the reader must not miss.

> [!WARNING]
> A consequence worth flagging before it bites.

> [!CAUTION]
> Genuine risk of data loss or breakage.

## Summary

> [!SUMMARY]
> - Callouts are plain markdown blockquotes carrying a `[!TYPE]` marker
> - Colours come from the theme palette, so they match the site they land on
> - Labels, colours, and icons are configurable per project

## FAQ

> [!FAQ]
> **How are callouts authored?**
> As GFM blockquotes, the same syntax GitHub uses.
>
> **Can an answer contain other blocks?**
> Yes. Lists, code, and links all work:
>
> - A list item
> - Another list item
>
> **What starts a new question?**
> A line that is entirely bold, and that either opens the callout or has a
> blank line above it. A bold lead-in sitting directly under the previous
> line stays part of that answer.
>
> **What happens on a theme without these palette slugs?**
> The box loses that colour rather than breaking, and the slug can be
> replaced with a hex literal in configuration.

## Bookmark

> [!BOOKMARK]
> /family-chore-chart-tablet/
