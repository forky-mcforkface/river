import math

from river import stats, utils
from river.stats import _rust_stats


class Quantile(stats.base.Univariate):
    """Running quantile.

    Uses the P² algorithm, which is also known as the "Piecewise-Parabolic quantile estimator".
    The code is inspired by LiveStat's implementation [^2].

    Parameters
    ----------
    q
        Determines which quantile to compute, must be comprised between 0 and 1.

    Examples
    --------

    >>> from river import stats
    >>> import numpy as np

    >>> np.random.seed(42 * 1337)
    >>> mu, sigma = 0, 1
    >>> s = np.random.normal(mu, sigma, 500)

    >>> median = stats.Quantile(0.5)
    >>> for x in s:
    ...    _ = median.update(x)

    >>> print(f'The estimated value of the 50th (median) quantile is {median.get():.4f}')
    The estimated value of the 50th (median) quantile is -0.0275
    >>> print(f'The real value of the 50th (median) quantile is {np.median(s):.4f}')
    The real value of the 50th (median) quantile is -0.0135

    >>> percentile_17 = stats.Quantile(0.17)
    >>> for x in s:
    ...    _ = percentile_17.update(x)

    >>> print(f'The estimated value of the 17th quantile is {percentile_17.get():.4f}')
    The estimated value of the 17th quantile is -0.8652
    >>> print(f'The real value of the 17th quantile is {np.percentile(s,17):.4f}')
    The real value of the 17th quantile is -0.9072

    References
    ----------
    [^1]: [The P² Algorithm for Dynamic Univariateal Computing Calculation of Quantiles and Editor Histograms Without Storing Observations](https://www.cse.wustl.edu/~jain/papers/ftp/psqr.pdf)
    [^2]: [LiveStats](https://github.com/cxxr/LiveStats)
    [^3]: [P² quantile estimator: estimating the median without storing values](https://aakinshin.net/posts/p2-quantile-estimator/)

    """

    def __init__(self, q=0.5):

        if not 0 < q < 1:
            raise ValueError("q is not comprised between 0 and 1")
        self.q = q

        self.desired_marker_position = [0, self.q / 2, self.q, (1 + self.q) / 2, 1]
        self.marker_position = [1, 1 + 2 * self.q, 1 + 4 * self.q, 3 + 2 * self.q, 5]
        self.position = list(range(1, 6))
        self.heights = []
        self.heights_sorted = False

    def _find_k(self, x):

        if x < self.heights[0]:
            self.heights[0] = x
            k = 1

        else:
            for i in range(1, 5):
                if self.heights[i - 1] <= x and x < self.heights[i]:
                    k = i
                    break
            else:
                k = 4
                if self.heights[-1] < x:
                    self.heights[-1] = x
        return k

    @classmethod
    def _compute_P2(cls, qp1, q, qm1, d, np1, n, nm1):

        d = float(d)
        n = float(n)
        np1 = float(np1)
        nm1 = float(nm1)

        outer = d / (np1 - nm1)
        inner_left = (n - nm1 + d) * (qp1 - q) / (np1 - n)
        inner_right = (np1 - n - d) * (q - qm1) / (n - nm1)

        return q + outer * (inner_left + inner_right)

    def _adjust(self):

        for i in range(1, 4):
            n = self.position[i]
            q = self.heights[i]

            d = self.marker_position[i] - n

            if (d >= 1 and self.position[i + 1] - n > 1) or (
                d <= -1 and self.position[i - 1] - n < -1
            ):
                d = int(math.copysign(1, d))

                qp1 = self.heights[i + 1]
                qm1 = self.heights[i - 1]
                np1 = self.position[i + 1]
                nm1 = self.position[i - 1]

                qn = self._compute_P2(qp1, q, qm1, d, np1, n, nm1)

                if qm1 < qn and qn < qp1:
                    self.heights[i] = qn
                else:
                    self.heights[i] = q + d * (self.heights[i + d] - q) / (self.position[i + d] - n)

                self.position[i] = n + d

        return self

    def update(self, x):

        # Initialisation
        if len(self.heights) != 5:
            self.heights.append(x)

        else:
            if not self.heights_sorted:
                self.heights.sort()
                self.heights_sorted = True

            # Find cell k such that qk < Xj <= qk+i and adjust extreme values (q1 and q) if necessary
            k = self._find_k(x)

            # Increment all positions greater than k
            self.position = [j if i < k else j + 1 for i, j in enumerate(self.position)]
            self.marker_position = [
                x + y for x, y in zip(self.marker_position, self.desired_marker_position)
            ]

            # Adjust heights of markers 2-4 if necessary
            self._adjust()

        return self

    def get(self):
        if self.heights_sorted:
            return self.heights[2]

        if self.heights:
            self.heights.sort()
            length = len(self.heights)
            return self.heights[int(min(max(length - 1, 0), length * self.q))]

        return None


class RollingQuantile(stats.base.RollingUnivariate):
    """Running quantile over a window.

    Parameters
    ----------
    q
        Determines which quantile to compute, must be comprised between 0 and 1.
    window_size
        Size of the window.

    Examples
    --------

    >>> from river import stats

    >>> rolling_quantile = stats.RollingQuantile(
    ...     q=.5,
    ...     window_size=101,
    ... )

    >>> for i in range(1001):
    ...     rolling_quantile = rolling_quantile.update(i)
    ...     if i % 100 == 0:
    ...         print(rolling_quantile.get())
    0.0
    50.0
    150.0
    250.0
    350.0
    450.0
    550.0
    650.0
    750.0
    850.0
    950.0

    References
    ----------
    [^1]: [Left sorted](https://stackoverflow.com/questions/8024571/insert-an-item-into-sorted-list-in-python)

    """

    def __init__(self, q, window_size):
        self.window = utils.SortedWindow(size=window_size)
        self.q = q
        idx = self.q * (self.window.size - 1)

        self._lower = int(math.floor(idx))
        self._higher = self._lower + 1
        if self._higher > self.window.size - 1:
            self._higher = self.window.size - 1
        self._frac = idx - self._lower

    def _prepare(self):
        if len(self.window) < self.window.size:
            idx = self.q * (len(self.window) - 1)
            lower = int(math.floor(idx))
            higher = lower + 1
            if higher > len(self.window) - 1:
                higher = len(self.window) - 1
            frac = idx - lower
            return lower, higher, frac

        return self._lower, self._higher, self._frac

    @property
    def window_size(self):
        return self.window.size

    def update(self, x):
        self.window.append(x)
        return self

    def get(self):
        lower, higher, frac = self._prepare()
        try:
            return self.window[lower] + (self.window[higher] - self.window[lower]) * frac
        except IndexError:
            return None


class FastQuantile(stats.base.Univariate):
    """Running quantile.
    Uses the P² algorithm, which is also known as the "Piecewise-Parabolic quantile estimator".
    The code is inspired by LiveStat's implementation [^2].
    Parameters
    ----------
    q
        Determines which quantile to compute, must be comprised between 0 and 1.
    Examples
    --------
    >>> from river import stats
    >>> import numpy as np
    >>> np.random.seed(42 * 1337)
    >>> mu, sigma = 0, 1
    >>> s = np.random.normal(mu, sigma, 500)
    >>> median = stats.FastQuantile(0.5)
    >>> for x in s:
    ...    _ = median.update(x)
    >>> print(f'The estimated value of the 50th (median) quantile is {median.get():.4f}')
    The estimated value of the 50th (median) quantile is -0.0275
    >>> print(f'The real value of the 50th (median) quantile is {np.median(s):.4f}')
    The real value of the 50th (median) quantile is -0.0135
    >>> percentile_17 = stats.FastQuantile(0.17)
    >>> for x in s:
    ...    _ = percentile_17.update(x)
    >>> print(f'The estimated value of the 17th quantile is {percentile_17.get():.4f}')
    The estimated value of the 17th quantile is -0.8652
    >>> print(f'The real value of the 17th quantile is {np.percentile(s,17):.4f}')
    The real value of the 17th quantile is -0.9072

    References
    ----------
    [^1]: [The P² Algorithm for Dynamic Univariateal Computing Calculation of Quantiles and Editor Histograms Without Storing Observations](https://www.cse.wustl.edu/~jain/papers/ftp/psqr.pdf)
    [^2]: [LiveStats](https://github.com/cxxr/LiveStats)
    [^3]: [P² quantile estimator: estimating the median without storing values](https://aakinshin.net/posts/p2-quantile-estimator/)
    """

    # Note for devs, if you want look the pure python implementation here:
    # https://github.com/online-ml/river/blob/40c3190c9d05671ae4c2dc8b76c163ea53a45fb0/river/stats/quantile.py
    def __init__(self, q: float = 0.5):
        super().__init__()
        if not 0 < q < 1:
            raise ValueError("q is not comprised between 0 and 1")
        self._quantile = _rust_stats.RsQuantile(q)
        self.is_updated = False
        self.q = q  # Used by anomaly.QuantileFilter

    def update(self, x):
        self._quantile.update(x)
        if not self.is_updated:
            self.is_updated = True
        return self

    def get(self):
        return self._quantile.get()

    def __repr__(self):
        # We surcharge this method to avoid this error on rust side:
        # pyo3_runtime.PanicException: index out of bounds: the len is 0 but the index is 0
        # This error is caused by the `get()` use before the update in the super method.
        value = None
        if self.is_updated:
            value = self.get()
        fmt_value = None if value is None else f"{value:{self._fmt}}".rstrip("0")
        return f"{self.__class__.__name__}: {fmt_value}"


class FastRollingQuantile(stats.base.RollingUnivariate):
    """Running quantile over a window.

    Parameters
    ----------
    q
        Determines which quantile to compute, must be comprised between 0 and 1.
    window_size
        Size of the window.

    Examples
    --------

    >>> from river import stats

    >>> rolling_quantile = stats.FastRollingQuantile(
    ...     q=.5,
    ...     window_size=101,
    ... )

    >>> for i in range(1001):
    ...     rolling_quantile = rolling_quantile.update(i)
    ...     if i % 100 == 0:
    ...         print(rolling_quantile.get())
    0.0
    50.0
    150.0
    250.0
    350.0
    450.0
    550.0
    650.0
    750.0
    850.0
    950.0

    References
    ----------
    [^1]: [Left sorted](https://stackoverflow.com/questions/8024571/insert-an-item-into-sorted-list-in-python)

    """

    # Note for devs, if you want look the pure python implementation here:
    # https://github.com/online-ml/river/blob/40c3190c9d05671ae4c2dc8b76c163ea53a45fb0/river/stats/quantile.py
    def __init__(self, q: float, window_size: int):

        super().__init__()
        if not 0 <= q <= 1:
            raise ValueError("q is not comprised between 0 and 1")
        self._rolling_quantile = _rust_stats.RsRollingQuantile(q, window_size)
        self.window_size_value = window_size
        self.is_updated = False

    def update(self, x):
        self._rolling_quantile.update(x)
        if not self.is_updated:
            self.is_updated = True
        return self

    def get(self):
        return self._rolling_quantile.get()

    @property
    def window_size(self):
        return self.window_size_value

    def __repr__(self):
        # We surcharge this method to avoid this error on rust side:
        # pyo3_runtime.PanicException: attempt to subtract with overflow
        # This error is caused by the `get()` use before the update in the super method.
        value = None
        if self.is_updated:
            value = self.get()
        fmt_value = None if value is None else f"{value:{self._fmt}}".rstrip("0")
        return f"{self.__class__.__name__}: {fmt_value}"
