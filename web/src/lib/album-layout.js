/* Telegram WebK grouped layout ported from the original vanilla implementation.
 * Keep this file as pure functions: it is the most layout-sensitive part of the UI. */

export const GAP = 1;

export const RectPart = { None: 0, Top: 1, Right: 2, Bottom: 4, Left: 8 };

const sum = (arr) => arr.reduce((s, v) => s + v, 0);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

export class Layouter {
  constructor(sizes, maxWidth, minWidth, spacing, maxHeight) {
    this.maxWidth = maxWidth;
    this.minWidth = minWidth;
    this.spacing = spacing;
    this.maxHeight = maxHeight ?? maxWidth;
    this.maxHeightConstraint = maxHeight;
    this.sizes = sizes;
    this.count = sizes.length;
    this.ratios = sizes.map((s) => s.w / s.h);
    this.proportions = this.ratios
      .map((r) => (r > 1.2 ? 'w' : r < 0.8 ? 'n' : 'q'))
      .join('');
    this.averageRatio = sum(this.ratios) / this.count;
    this.maxSizeRatio = maxWidth / this.maxHeight;
  }

  layout() {
    if (!this.count) return [];
    if (this.count === 1) return this._layoutOne();
    if (this.count >= 5 || this.ratios.some((r) => r > 2)) {
      return new ComplexLayouter(
        this.ratios,
        this.averageRatio,
        this.maxWidth,
        this.minWidth,
        this.spacing,
        this.maxHeightConstraint,
      ).layout();
    }
    if (this.count === 2) return this._layoutTwo();
    if (this.count === 3) return this._layoutThree();
    return this._layoutFour();
  }

  _layoutOne() {
    const width = this.maxWidth;
    const naturalHeight = (this.sizes[0].h * width) / this.sizes[0].w;
    const height = this.maxHeightConstraint === undefined
      ? naturalHeight
      : Math.min(naturalHeight, this.maxHeight);
    return [{
      geometry: { x: 0, y: 0, width, height },
      sides: RectPart.Left | RectPart.Top | RectPart.Right | RectPart.Bottom,
    }];
  }

  _layoutTwo() {
    if (
      this.proportions === 'ww' &&
      this.averageRatio > 1.4 * this.maxSizeRatio &&
      this.ratios[1] - this.ratios[0] < 0.2
    ) {
      return this._layoutTwoTopBottom();
    }
    if (this.proportions === 'ww' || this.proportions === 'qq') {
      return this._layoutTwoLeftRightEqual();
    }
    return this._layoutTwoLeftRight();
  }

  _layoutTwoTopBottom() {
    const w = this.maxWidth;
    const h = Math.round(
      Math.min(
        w / this.ratios[0],
        w / this.ratios[1],
        (this.maxHeight - this.spacing) / 2,
      ),
    );
    return [
      {
        geometry: { x: 0, y: 0, width: w, height: h },
        sides: RectPart.Left | RectPart.Top | RectPart.Right,
      },
      {
        geometry: { x: 0, y: h + this.spacing, width: w, height: h },
        sides: RectPart.Left | RectPart.Bottom | RectPart.Right,
      },
    ];
  }

  _layoutTwoLeftRightEqual() {
    const w = Math.round((this.maxWidth - this.spacing) / 2);
    const h = Math.round(
      Math.min(w / this.ratios[0], w / this.ratios[1], this.maxHeight),
    );
    return [
      {
        geometry: { x: 0, y: 0, width: w, height: h },
        sides: RectPart.Top | RectPart.Left | RectPart.Bottom,
      },
      {
        geometry: { x: w + this.spacing, y: 0, width: w, height: h },
        sides: RectPart.Top | RectPart.Right | RectPart.Bottom,
      },
    ];
  }

  _layoutTwoLeftRight() {
    const minW = Math.round(this.minWidth * 1.5);
    const sw = Math.min(
      Math.round(
        Math.max(
          0.4 * (this.maxWidth - this.spacing),
          (this.maxWidth - this.spacing) /
            this.ratios[0] /
            (1 / this.ratios[0] + 1 / this.ratios[1]),
        ),
      ),
      this.maxWidth - this.spacing - minW,
    );
    const fw = this.maxWidth - sw - this.spacing;
    const h = Math.min(
      this.maxHeight,
      Math.round(Math.min(fw / this.ratios[0], sw / this.ratios[1])),
    );
    return [
      {
        geometry: { x: 0, y: 0, width: fw, height: h },
        sides: RectPart.Top | RectPart.Left | RectPart.Bottom,
      },
      {
        geometry: { x: fw + this.spacing, y: 0, width: sw, height: h },
        sides: RectPart.Top | RectPart.Right | RectPart.Bottom,
      },
    ];
  }

  _layoutThree() {
    if (this.proportions[0] === 'n') return this._layoutThreeLeftAndOther();
    return this._layoutThreeTopAndOther();
  }

  _layoutThreeLeftAndOther() {
    const fh = this.maxHeight;
    const th = Math.round(
      Math.min(
        (this.maxHeight - this.spacing) / 2,
        (this.ratios[1] * (this.maxWidth - this.spacing)) /
          (this.ratios[2] + this.ratios[1]),
      ),
    );
    const sh = fh - th - this.spacing;
    const rw = Math.max(
      this.minWidth,
      Math.round(
        Math.min(
          (this.maxWidth - this.spacing) / 2,
          Math.min(th * this.ratios[2], sh * this.ratios[1]),
        ),
      ),
    );
    const lw = Math.min(
      Math.round(fh * this.ratios[0]),
      this.maxWidth - this.spacing - rw,
    );
    return [
      {
        geometry: { x: 0, y: 0, width: lw, height: fh },
        sides: RectPart.Top | RectPart.Left | RectPart.Bottom,
      },
      {
        geometry: { x: lw + this.spacing, y: 0, width: rw, height: sh },
        sides: RectPart.Top | RectPart.Right,
      },
      {
        geometry: {
          x: lw + this.spacing,
          y: sh + this.spacing,
          width: rw,
          height: th,
        },
        sides: RectPart.Bottom | RectPart.Right,
      },
    ];
  }

  _layoutThreeTopAndOther() {
    const fw = this.maxWidth;
    const fh = Math.round(
      Math.min(fw / this.ratios[0], (this.maxHeight - this.spacing) * 0.66),
    );
    const sw = Math.round((this.maxWidth - this.spacing) / 2);
    const sh = Math.min(
      this.maxHeight - fh - this.spacing,
      Math.round(Math.min(sw / this.ratios[1], sw / this.ratios[2])),
    );
    const tw = fw - sw - this.spacing;
    return [
      {
        geometry: { x: 0, y: 0, width: fw, height: fh },
        sides: RectPart.Left | RectPart.Top | RectPart.Right,
      },
      {
        geometry: { x: 0, y: fh + this.spacing, width: sw, height: sh },
        sides: RectPart.Bottom | RectPart.Left,
      },
      {
        geometry: {
          x: sw + this.spacing,
          y: fh + this.spacing,
          width: tw,
          height: sh,
        },
        sides: RectPart.Bottom | RectPart.Right,
      },
    ];
  }

  _layoutFour() {
    if (this.proportions[0] === 'w') return this._layoutFourTopAndOther();
    return this._layoutFourLeftAndOther();
  }

  _layoutFourTopAndOther() {
    const w = this.maxWidth;
    const h0 = Math.round(
      Math.min(w / this.ratios[0], (this.maxHeight - this.spacing) * 0.66),
    );
    const h = Math.round(
      (this.maxWidth - 2 * this.spacing) /
        (this.ratios[1] + this.ratios[2] + this.ratios[3]),
    );
    const w0 = Math.max(
      this.minWidth,
      Math.round(
        Math.min((this.maxWidth - 2 * this.spacing) * 0.4, h * this.ratios[1]),
      ),
    );
    const w2 = Math.round(
      Math.max(
        Math.max(this.minWidth, (this.maxWidth - 2 * this.spacing) * 0.33),
        h * this.ratios[3],
      ),
    );
    const w1 = w - w0 - w2 - 2 * this.spacing;
    const h1 = Math.min(this.maxHeight - h0 - this.spacing, h);
    return [
      {
        geometry: { x: 0, y: 0, width: w, height: h0 },
        sides: RectPart.Left | RectPart.Top | RectPart.Right,
      },
      {
        geometry: { x: 0, y: h0 + this.spacing, width: w0, height: h1 },
        sides: RectPart.Bottom | RectPart.Left,
      },
      {
        geometry: {
          x: w0 + this.spacing,
          y: h0 + this.spacing,
          width: w1,
          height: h1,
        },
        sides: RectPart.Bottom,
      },
      {
        geometry: {
          x: w0 + this.spacing + w1 + this.spacing,
          y: h0 + this.spacing,
          width: w2,
          height: h1,
        },
        sides: RectPart.Right | RectPart.Bottom,
      },
    ];
  }

  _layoutFourLeftAndOther() {
    const h = this.maxHeight;
    const w0 = Math.round(
      Math.min(h * this.ratios[0], (this.maxWidth - this.spacing) * 0.6),
    );
    const w = Math.round(
      (this.maxHeight - 2 * this.spacing) /
        (1 / this.ratios[1] + 1 / this.ratios[2] + 1 / this.ratios[3]),
    );
    const h0 = Math.round(w / this.ratios[1]);
    const h1 = Math.round(w / this.ratios[2]);
    const h2 = h - h0 - h1 - 2 * this.spacing;
    const w1 = Math.max(
      this.minWidth,
      Math.min(this.maxWidth - w0 - this.spacing, w),
    );
    return [
      {
        geometry: { x: 0, y: 0, width: w0, height: h },
        sides: RectPart.Top | RectPart.Left | RectPart.Bottom,
      },
      {
        geometry: { x: w0 + this.spacing, y: 0, width: w1, height: h0 },
        sides: RectPart.Top | RectPart.Right,
      },
      {
        geometry: {
          x: w0 + this.spacing,
          y: h0 + this.spacing,
          width: w1,
          height: h1,
        },
        sides: RectPart.Right,
      },
      {
        geometry: {
          x: w0 + this.spacing,
          y: h0 + h1 + 2 * this.spacing,
          width: w1,
          height: h2,
        },
        sides: RectPart.Bottom | RectPart.Right,
      },
    ];
  }
}

class ComplexLayouter {
  constructor(ratios, averageRatio, maxWidth, minWidth, spacing, maxHeight) {
    this.ratios = ComplexLayouter._cropRatios(ratios, averageRatio);
    this.averageRatio = averageRatio;
    this.count = ratios.length;
    this.maxWidth = maxWidth;
    this.minWidth = minWidth;
    this.spacing = spacing;
    this.maxHeight = maxHeight ?? (maxWidth * 4) / 3;
    this.constrainHeight = maxHeight !== undefined;
  }

  static _cropRatios(ratios, averageRatio) {
    const kMax = 2.75;
    const kMin = 0.6667;
    return ratios.map((r) =>
      averageRatio > 1.1 ? clamp(r, 1, kMax) : clamp(r, kMin, 1),
    );
  }

  layout() {
    const result = new Array(this.count);
    const attempts = [];

    const multiHeight = (offset, count) => {
      const ratios = this.ratios.slice(offset, offset + count);
      return (this.maxWidth - (count - 1) * this.spacing) / sum(ratios);
    };

    const pushAttempt = (lineCounts) => {
      const heights = [];
      let offset = 0;
      for (const cnt of lineCounts) {
        heights.push(multiHeight(offset, cnt));
        offset += cnt;
      }
      attempts.push({ lineCounts, heights });
    };

    for (let first = 1; first < this.count; ++first) {
      const second = this.count - first;
      if (first > 3 || second > 3) continue;
      pushAttempt([first, second]);
    }
    for (let first = 1; first < this.count - 1; ++first) {
      for (let second = 1; second < this.count - first; ++second) {
        const third = this.count - first - second;
        if (first > 3 || second > (this.averageRatio < 0.85 ? 4 : 3) || third > 3) {
          continue;
        }
        pushAttempt([first, second, third]);
      }
    }
    for (let first = 1; first < this.count - 1; ++first) {
      for (let second = 1; second < this.count - first; ++second) {
        for (let third = 1; third < this.count - first - second; ++third) {
          const fourth = this.count - first - second - third;
          if (first > 3 || second > 3 || third > 3 || fourth > 3) continue;
          pushAttempt([first, second, third, fourth]);
        }
      }
    }

    let optimalAttempt = null;
    let optimalDiff = 0;
    for (const attempt of attempts) {
      const { heights, lineCounts: counts } = attempt;
      const lineCount = counts.length;
      const totalHeight = sum(heights) + this.spacing * (lineCount - 1);
      const minLineHeight = Math.min(...heights);
      const bad1 = minLineHeight < this.minWidth ? 1.5 : 1;
      let bad2 = 1;
      for (let line = 1; line < lineCount; ++line) {
        if (counts[line - 1] > counts[line]) {
          bad2 = 1.5;
          break;
        }
      }
      const diff = Math.abs(totalHeight - this.maxHeight) * bad1 * bad2;
      if (!optimalAttempt || diff < optimalDiff) {
        optimalAttempt = attempt;
        optimalDiff = diff;
      }
    }

    const optimalCounts = optimalAttempt.lineCounts;
    const optimalHeights = optimalAttempt.heights;
    const rowCount = optimalCounts.length;

    const naturalHeight = sum(optimalHeights) + this.spacing * (rowCount - 1);
    const heightScale = this.constrainHeight && naturalHeight > this.maxHeight
      ? Math.max(0, this.maxHeight - this.spacing * (rowCount - 1)) / sum(optimalHeights)
      : 1;
    let accumulatedScaledHeight = 0;
    const scaledHeights = optimalHeights.map((height, row) => {
      let scaledHeight;
      if (heightScale === 1) {
        scaledHeight = Math.round(height);
      } else if (row !== rowCount - 1) {
        scaledHeight = Math.floor(height * heightScale);
      } else {
        scaledHeight = Math.max(
          0,
          this.maxHeight - this.spacing * (rowCount - 1) - accumulatedScaledHeight,
        );
      }
      accumulatedScaledHeight += scaledHeight;
      return scaledHeight;
    });

    let index = 0;
    let y = 0;
    for (let row = 0; row < rowCount; ++row) {
      const colCount = optimalCounts[row];
      const lineHeight = optimalHeights[row];
      const height = scaledHeights[row];
      let x = 0;
      for (let col = 0; col < colCount; ++col) {
        const sides =
          (row === 0 ? RectPart.Top : 0) |
          (row === rowCount - 1 ? RectPart.Bottom : 0) |
          (col === 0 ? RectPart.Left : 0) |
          (col === colCount - 1 ? RectPart.Right : 0);
        const width =
          col === colCount - 1
            ? this.maxWidth - x
            : Math.round(this.ratios[index] * lineHeight);
        result[index] = { geometry: { x, y, width, height }, sides };
        x += width + this.spacing;
        ++index;
      }
      y += height + this.spacing;
    }
    return result;
  }
}

export function computeAlbumLayout(items, maxWidth) {
  const sizes = items.map((it) => ({ w: it.width || 1, h: it.height || 1 }));
  return new Layouter(sizes, maxWidth, 100, GAP).layout();
}
