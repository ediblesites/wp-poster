---
post_type: faxfaq
title: Testing Inline Images with Figure/Figcaption
slug: test-inline-images
status: draft
excerpt: Testing local and remote images in post content
taxonomies:
  faqtype: Test
---

# Testing Inline Images

This post demonstrates how to include images in the content with automatic figure/figcaption wrapping.

## Local Image

Here's a local image that will be uploaded to WordPress:

![Local test image](blablabla.jpg "This is a local image caption")

The local image gets uploaded to your WordPress media library and the URL is automatically updated.

## Remote Image

Here's a remote image that can be used directly:

![Remote test image](https://picsum.photos/600/400 "This is a remote image caption")

Remote images can be used directly or optionally uploaded to WordPress (currently set to use directly for performance).

## Image Without Caption

![](https://picsum.photos/400/300)

Even without alt text or title, the image still gets wrapped in figure tags.

## Image With Only Alt Text

![Alternative text only](https://picsum.photos/500/300)

When there's only alt text, it's used as the figcaption.

## Conclusion

All images are automatically wrapped in `<figure>` and `<figcaption>` tags as requested!