"""
:class:`AudioSignal` is the main entry and exit point for all source separation algorithms
in *nussl*.

The :class:`AudioSignal` class is a container for all things related to audio data. It contains
utilities for input/output, time-series and frequency domain manipulation, plotting, and much
more. The :class:`AudioSignal` class is used in all source separation objects in *nussl*.

:class:`AudioSignal` object stores time-series audio data as a 2D `numpy` array in
:attr:`audio_data` (see :attr:`audio_data` for details) and stores Short-Time Fourier Transform
data as 3D `numpy` array in :ref:`stft_data` (see :attr:`stft_data` for details).

There are a few options for initializing an `AudioSignal` object. The first is to initialize an
empty `AudioSignal` object, with no parameters:

 >>> signal = nussl.AudioSignal()

In this case, there is no data stored in :attr:`audio_data` or in :attr:`stft_data`, though
these attributes can be updated at any time after the object has been created.

Additionally, an `AudioSignal` object can be loaded with exactly one of the following:

    1. A path to an input audio file (see :func:`load_audio_from_file` for details).
    2. A `numpy` array of 1D or 2D real-valued time-series audio data.
    3. A `numpy` array of 2D or 3D complex-valued time-frequency STFT data.

:class:`AudioSignal` will throw an error if it is initialized with more than one of the
previous at once.

Here are examples of all three of these cases:

 .. code-block:: python
    :linenos:

    import numpy as np
    import nussl

    # Initializing an empty AudioSignal object:
    sig_empty = nussl.AudioSignal()

    # Initializing from a path:
    file_path = 'my/awesome/mixture.wav'
    sig_path = nussl.AudioSignal(file_path)

    # Initializing with a 1D or 2D numpy array containing audio data:
    aud_1d = np.sin(np.linspace(0.0, 1.0, 48000))
    sig_1d = nussl.AudioSignal(audio_data_array=aud_1d, sample_rate=48000)

    # FYI: The shape doesn't matter, nussl will correct for it
    aud_2d = np.array([aud_1d, -2 * aud_1d])
    sig_2d = nussl.AudioSignal(audio_data_array=aud_2d)

    # Initializing with a 2D or 3D numpy array containing STFT data:
    stft_2d = np.random.rand((1024, 3000)) + 1j * np.random.rand((1024, 3000))
    sig_stft_2d = nussl.AudioSignal(stft=stft_2d)

    # Two channels of STFT data:
    stft_3d = nussl.utils.complex_randn((1024, 3000, 2))
    sig_stft_3d = nussl.AudioSignal(stft=stft_3d)

    # Initializing with more than one of the above methods will raise an exception:
    sig_exception = nussl.AudioSignal(audio_data_array=aud_2d, stft=stft_2d)

When initializing from a path, `AudioSignal` can read many types of audio files, provided that
your computer has the backends installed to understand the corresponding codecs. *nussl* uses
*librosa*'s `load` function to read in audio data. See librosa's documentation for details:
https://github.com/librosa/librosa#audioread

The sample rate of an `AudioSignal` object is set upon initialization. If initializing from a
path, the sample rate of the `AudioSignal` object inherits the native sample rate from the file.
If initialized via method 2 or 3 from above, the sample rate is passed in as an optional
argument. In these cases, with no sample rate explicitly defined, the default sample rate is
44.1 kHz (CD quality). If this argument is provided when reading from a file and the provided
sample rate does not match the native sample rate of the file, `AudioSignal` will resample the
data from the file so that it matches the provided sample rate.

Once initialized with a single type of data (time-series or time-frequency), there are methods
to compute an STFT from time-series data (:func:`stft`) and vice versa (:func:`istft`).

Notes:
    There is no guarantee that data in :attr:`audio_data` corresponds to data in
    :attr:`stft_data`. E.g., when an :class:`AudioSignal` object is initialized with
    :attr:`audio_data` of an audio mixture, its :attr:`stft_data` is `None` until :func:`stft`
    is called. Once :func:`stft` is called and a mask is applied to :attr:`stft_data` (via some
    algorithm), the :attr:`audio_data` in this :class:`AudioSignal` object still contains data
    from the original mixture that it was initialized with even though :attr:`stft_data`
    contains altered data. (To hear the results, simply call :func:`istft` on the
    :class:`AudioSignal` object.) It is up to the user to keep track of the contents of
    :attr:`audio_data` and :attr:`stft_data`.

See Also:
    For a walk-through of AudioSignal features, see :ref:`audio_signal_basics` and
    :ref:`audio_signal_stft`.

"""


import copy
import json
import numbers
import os.path
import warnings
from collections import namedtuple

import audioread
import librosa
import matplotlib.pyplot as plt
import numpy as np
import scipy.io.wavfile as wav
import scipy
from scipy.signal import check_COLA
import soundfile as sf

from . import constants
from . import utils
from . import masks

__all__ = ['AudioSignal']

"""
STFTParams object is a container that holds STFT parameters - window_length, 
hop_length, and window_type. Not all parameters need to be specified. Ones that
are not specified will be inferred by the AudioSignal parameters and the settings
in nussl.constants.
"""
STFTParams = namedtuple('STFTParams',
    ['window_length', 'hop_length', 'window_type'],
    defaults=(None, None, None))


class AudioSignal(object):
    """
    Arguments:
        path_to_input_file (str): Path to an input file to load upon initialization. Audio
            gets loaded into :attr:`audio_data`.
        audio_data_array (:obj:`np.ndarray`): 1D or 2D numpy array containing a real-valued,
            time-series representation of the audio.
        stft (:obj:`np.ndarray`): 2D or 3D numpy array containing pre-computed complex-valued STFT
            data.
        label (str): A label for this :class:`AudioSignal` object.
        offset (float): Starting point of the section to be extracted (in seconds) if initializing
            from  a file.
        duration (float): Length of the signal to read from the file (in seconds). Defaults to full
            length of the signal.
        sample_rate (int): Sampling rate of this :class:`AudioSignal` object.

    Attributes:
        audio_data (:obj:`np.ndarray`):
            Real-valued, uncompressed, time-domain representation of the audio.
            2D numpy array with shape `(n_channels, n_samples)`.
            ``None`` by default.
            Stored as an array of floats.
            It is possible to change how much of :attr:`audio_data` is accessible outside of this
            :class:`AudioSignal` object by changing the 'active region'.
            See :func:`set_active_region_to_default` for more details.
        path_to_input_file (str): Path to the input file. ``None`` if this AudioSignal never loaded
            a file, i.e., initialized with a `np.ndarray`.
        sample_rate (int): Sample rate of this :class:`AudioSignal` object.
        stft_data (:obj:`np.ndarray`): Complex-valued, frequency-domain representation of audio
            calculated by :func:`stft` or provided upon initialization.
            3D :obj:`numpy` array with shape `(n_frequency_bins, n_hops, n_channels)`.
            ``None`` by default.
        stft_params (:obj:`STFTParams`): Container for all settings for doing a STFT. Has same
            lifespan as :class:`AudioSignal` object.
        label (str): A label for this :class:`AudioSignal` object.
  
    """

    def __init__(self, path_to_input_file=None, audio_data_array=None, stft=None, label=None,
                 sample_rate=None, stft_params=None, offset=0, duration=None):

        self.path_to_input_file = path_to_input_file
        self._audio_data = None
        self.original_signal_length = None
        self._stft_data = None
        self._sample_rate = None
        self._active_start = None
        self._active_end = None
        self.label = label

        # Assert that this object was only initialized in one way
        got_path = path_to_input_file is not None
        got_audio_array = audio_data_array is not None
        got_stft = stft is not None
        init_inputs = np.array([got_path, got_audio_array, got_stft])

        # noinspection PyPep8
        if len(init_inputs[init_inputs == True]) > 1:  # ignore inspection for clarity
            raise AudioSignalException('Can only initialize AudioSignal object with one and only '
                                       'one of {path, audio, stft}!')

        if path_to_input_file is not None:
            self.load_audio_from_file(self.path_to_input_file, offset, duration, sample_rate)
        elif audio_data_array is not None:
            self.load_audio_from_array(audio_data_array, sample_rate)

        if self._sample_rate is None:
            self._sample_rate = constants.DEFAULT_SAMPLE_RATE \
                if sample_rate is None else sample_rate

        self.stft_data = stft  # complex spectrogram data
        self.stft_params = stft_params
        
    def __str__(self):
        return (
            f"{self.__class__.__name__} "
            f"({self.label if self.label else 'unlabeled'}): "
            f"{self.num_channels if self.num_channels else '[unknown]'} ch, "
            f"{self.signal_duration if self.signal_duration else '[unknown]'} sec @ "
            f"{self.path_to_input_file if self.path_to_input_file else 'path unknown'}"
        )

    ##################################################
    #                 Properties
    ##################################################

    # Constants for accessing _audio_data np.array indices
    _LEN = 1
    _CHAN = 0

    _STFT_BINS = 0
    _STFT_LEN = 1
    _STFT_CHAN = 2

    @property
    def signal_length(self):
        """
        (int): Number of samples in the active region of :attr:`audio_data`.
        The length of the audio signal represented by this object in samples.

        See Also:
            :func:`set_active_region_to_default` for information about active regions.
        """
        if self.audio_data is None:
            return self.original_signal_length
        return self.audio_data.shape[constants.LEN_INDEX]

    @property
    def signal_duration(self):
        """
        (float): Duration of the active region of :attr:`audio_data` in seconds.
        The length of the audio signal represented by this object in seconds.

        See Also:
            :func:`set_active_region_to_default` for information about active regions.
        """
        if self.signal_length is None:
            return None
        return self.signal_length / self.sample_rate

    @property
    def num_channels(self):
        """
        (int): Number of channels this AudioSignal has.
        Defaults to returning number of channels in :attr:`audio_data`. If that is ``None``,
        returns number of channels in :attr:`stft_data`. If both are ``None`` then returns
        ``None``.

        See Also:
            * :func:`is_mono`
            * :func:`is_stereo`
        """
        # TODO: what about a mismatch between audio_data and stft_data??
        if self.audio_data is not None:
            return self.audio_data.shape[constants.CHAN_INDEX]
        if self.stft_data is not None:
            return self.stft_data.shape[constants.STFT_CHAN_INDEX]
        return None

    @property
    def is_mono(self):
        """
        Returns:
            (bool): Whether or not this signal is mono (i.e., has exactly `one` channel). First
            looks at :attr:`audio_data`, then (if that's `None`) looks at :attr:`stft_data`.

        See Also:
            * :func:`num_channels`
            * :func:`is_stereo`
        """
        return self.num_channels == 1

    @property
    def is_stereo(self):
        """
        Returns:
            (bool): Whether or not this signal is stereo (i.e., has exactly `two` channels). First
            looks at :attr:`audio_data`, then (if that's `None`) looks at :attr:`stft_data`.

        See Also:
            * :func:`num_channels`
            * :func:`is_mono`
        """
        return self.num_channels == 2

    @property
    def audio_data(self):
        """
        Stored as a :obj:`np.ndarray`, :attr:`audio_data` houses the raw PCM waveform data in the
        :class:`AudioSignal`. ``None`` by default, can be initialized at instantiation or set at
        any time by accessing this attribute or calling :func:`load_audio_from_array`. It is
        recommended to set :attr:`audio_data` by using :func:`load_audio_from_array` if this
        :class:`AudioSignal` has been initialized without any audio or STFT data.

        The audio data is stored with shape `(n_channels, n_samples)` as an array of floats.

        See Also:
            * :func:`load_audio_from_file` to load audio into :attr:`audio_data` after
            initialization.

            * :func:`load_audio_from_array` to safely load autio into :attr:`audio_data` after
            initialization.

            * :func:`set_active_region_to_default` for more information about the active region.

            * :attr:`signal_duration` and :attr:`signal_length` for length of audio data in seconds
            and samples, respectively.

            * :func:`stft` to calculate an STFT from this data,
            and :func:`istft` to calculate the inverse STFT and put it in :attr:`audio_data`.

            * :attr:`has_audio_data` to check if this attribute is empty or not.

            * :func:`plot_time_domain` to create a plot of audio data stored in this attribute.

            * :func:`peak_normalize` to apply gain such that to the
            absolute max value is exactly ``1.0``.

            * :func:`rms` to calculate the root-mean-square of :attr:`audio_data`

            * :func:`apply_gain` to apply a gain.

            * :func:`get_channel` to safely retrieve a single channel in :attr:`audio_data`.

        Notes:
            * This attribute only returns values within the active region. For more information
            see :func:`set_active_region_to_default`. When setting this attribute, the active
            region are reset to default.

            * :attr:`audio_data` and :attr:`stft_data` are not automatically synchronized, meaning
            that if one of them is changed, those changes are not instantly reflected in the other.
            To propagate changes, either call :func:`stft` or :func:`istft`.

            * If :attr:`audio_data` is set with an improperly transposed array, it will
            automatically transpose it so that it is set the expected way. A warning will be
            displayed on the console.

        Raises:
        :class:`AudioSignalException` if set with anything other than a finite-valued, 2D
        :obj:`np.ndarray`.

        Returns:
        (:obj:`np.ndarray`)
            Real-valued, uncompressed, time-domain representation of the audio. 2D ``numpy``
            array with shape `(n_channels, n_samples)`. ``None`` by default, this can be
            initialized at instantiation.  By default audio data is stored as an array of floats.
        """
        if self._audio_data is None:
            return None

        start = 0
        end = self._audio_data.shape[constants.LEN_INDEX]

        if self._active_end is not None and self._active_end < end:
            end = self._active_end

        if self._active_start is not None and self._active_start > 0:
            start = self._active_start

        return self._audio_data[:, start:end]

    @audio_data.setter
    def audio_data(self, value):

        if value is None:
            self._audio_data = None
            return

        elif not isinstance(value, np.ndarray):
            raise AudioSignalException('Type of self.audio_data must be of type np.ndarray!')

        if not np.isfinite(value).all():
            raise AudioSignalException('Not all values of audio_data are finite!')

        if value.ndim > 1 and value.shape[constants.CHAN_INDEX] > value.shape[constants.LEN_INDEX]:
            value = value.T

        if value.ndim > 2:
            raise AudioSignalException('self.audio_data cannot have more than 2 dimensions!')

        if value.ndim < 2:
            value = np.expand_dims(value, axis=constants.CHAN_INDEX)

        self._audio_data = value

        self.set_active_region_to_default()

    @property
    def stft_data(self):
        """
        Stored as a :obj:`np.ndarray`, :attr:`stft_data` houses complex-valued data computed from
        a Short-time Fourier Transform (STFT) of audio data in the :class:`AudioSignal`. ``None``
        by default, this :class:`AudioSignal` object can be initialized with STFT data upon
        initialization or it can be set at any time.

        The STFT data is stored with shape `(n_frequency_bins, n_hops, n_channels)` as an array of
        complex floats.

        See Also:
            * :func:`stft` to calculate an STFT from :attr:`audio_data`, and :func:`istft` to
            calculate the inverse STFT from this attribute and put it in :attr:`audio_data`.

            * :attr:`magnitude_spectrogram` to calculate and get the magnitude spectrogram from
            :attr:`stft_data`. :attr:`power_spectrogram` to calculate and get the power spectrogram
            from :attr:`stft_data`.

            * :func:`get_stft_channel` to safely get a specific channel in :attr:`stft_data`.

        Notes:
            * :attr:`audio_data` and :attr:`stft_data` are not automatically synchronized, meaning
            that if one of them is changed, those changes are not instantly reflected in the other.
            To propagate changes, either call :func:`stft` or :func:`istft`.

            * :attr:`stft_data` will expand a two dimensional array so that it has the expected
            shape `(n_frequency_bins, n_hops, n_channels)`.

        Raises:
        :class:`AudioSignalException` if set with an :obj:`np.ndarray` with one dimension or
        more than three dimensions.

        Returns:
        (:obj:`np.ndarray`)
            Complex-valued, time-frequency representation of the audio.
            3D `numpy` array with shape `(n_frequency_bins, n_hops, n_channels)`.
            ``None`` by default.
        """

        return self._stft_data

    @stft_data.setter
    def stft_data(self, value):
        if value is None:
            self._stft_data = None
            return

        elif not isinstance(value, np.ndarray):
            raise AudioSignalException('Type of self.stft_data must be of type np.ndarray!')

        if value.ndim == 1:
            raise AudioSignalException('Cannot support arrays with less than 2 dimensions!')

        if value.ndim == 2:
            value = np.expand_dims(value, axis=constants.STFT_CHAN_INDEX)

        if value.ndim > 3:
            raise AudioSignalException('Cannot support arrays with more than 3 dimensions!')

        if not np.iscomplexobj(value):
            warnings.warn('Initializing STFT with data that is non-complex. '
                          'This might lead to weird results!')

        self._stft_data = value

    @property
    def stft_params(self):
        """
        STFT parameters are kept in this property. STFT parameters are a namedtuple
        called STFTParams with the following signature:

        .. code-block:: python

            STFTParams(
                window_length=2048,
                hop_length=512,
                window_type='hann'
            )

        The defaults are 32ms windows, 8ms hop, and a hann window.
        
        Returns:
            STFTParams: STFTParams object used to take STFT and ISTFT for this
                AudioSignal.
        """
        return self._stft_params

    @stft_params.setter
    def stft_params(self, value):
        """
        Sets the STFT parameters for this AudioSignal object. If `value` is None, then
        the default STFT parameters are used (window of 32ms with an 8ms hop and a 
        hann window). If `value` is an STFTParams object, it is first validated and
        then set. If attributes that should be in STFTParams (e.g. window_type) are missing
        in `value`, then they are replaced with the defaults. Finally, the STFT
        parameters are checked to make sure that ISTFT will reconstruct the
        original audio faithfully via scipy.signal.check_COLA.
        
        Args:
            value (STFTParams or None): the STFTParams object (or None) that self.stft_params
                should be set to.
        """
        if value and not isinstance(value, STFTParams):
            raise ValueError("stft_params must be of type STFTParams or None!")

        default_win_len = int(
            2 ** (np.ceil(np.log2(
                constants.DEFAULT_WIN_LEN_PARAM * self.sample_rate))
        ))
        default_hop_len = default_win_len // 4
        default_win_type = constants.WINDOW_DEFAULT

        default_stft_params = STFTParams(
            window_length=default_win_len,
            hop_length=default_hop_len,
            window_type=default_win_type
        )._asdict()

        value = value._asdict() if value else default_stft_params

        for key in default_stft_params:
            if value[key] is None:
                value[key] = default_stft_params[key]
        
        self._stft_params = STFTParams(**value)
        if self._stft_params.window_type == 'sqrt_hann':
            window_type = constants.WINDOW_HANN
        else:
            window_type = self._stft_params.window_type
        check_COLA(
            window_type,
            self._stft_params.window_length,
            self._stft_params.hop_length)

    @property
    def has_data(self):
        """
        Returns `False` if :attr:`audio_data` and :attr:`stft_data` are empty. Else, returns `True`.
        
        Returns:
            Returns `False` if :attr:`audio_data` and :attr:`stft_data` are empty.
            Else, returns `True`.
        """
        has_audio_data = self.audio_data is not None and self.audio_data.size != 0
        has_stft_data = self.stft_data is not None and self.stft_data.size != 0
        return has_audio_data or has_stft_data

    @property
    def file_name(self):
        """
        (str): The name of the file wth extension (NOT the full path).
        
        Notes:
            This will return ``None`` if this :class:`AudioSignal` object was not
            loaded from a file.
        
        See Also:
            :attr:`path_to_input_file` for the full path.
        """
        if self.path_to_input_file is not None:
            return os.path.basename(self.path_to_input_file)
        return None

    @property
    def sample_rate(self):
        """
        Sample rate associated with the :attr:`audio_data` for this :class:`AudioSignal` object. If
        audio was read from a file, the sample rate will be set to the sample rate associated with
        the file. If this :class:`AudioSignal` object was initialized from an array (either through
        the constructor or through :func:`load_audio_from_array`) then the sample rate is set upon
        init.

        See Also:
            * :func:`resample` to change the sample rate and resample data in :attr:`sample_rate`.

            * :func:`load_audio_from_array` to read audio from an array and set the sample rate.

            * :var:`nussl.constants.DEFAULT_SAMPLE_RATE` the default sample rate for *nussl*
                if not specified

        Notes:
            This property is read-only and cannot be set directly.

        Returns:
            (int) Sample rate for this :class:`AudioSignal` object. Cannot be changed directly.
            Can only be set upon initialization or by using :func:`resample`.
        """
        return self._sample_rate

    @property
    def time_vector(self):
        """
        Returns:
            (:obj:`np.ndarray`): A 1D :obj:`np.ndarray` with timestamps (in seconds) for each sample
            in :attr:`audio_data`.
        """
        if self.signal_duration is None:
            return None
        return np.linspace(0.0, self.signal_duration, num=self.signal_length)

    @property
    def freq_vector(self):
        """
        Raises:
            :class:`AudioSignalException`: If :attr:`stft_data` is ``None``. Run :func:`stft` before
                accessing this.

        Returns:
            (:obj:`np.ndarray`): A 1D numpy array with frequency values that correspond
            to each frequency bin (vertical axis) for :attr:`stft_data`. Assumes linearly spaced
            frequency bins.
        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot calculate freq_vector until self.stft() is run')
        return np.linspace(0.0, self.sample_rate // 2,
                           num=self.stft_data.shape[constants.STFT_VERT_INDEX])

    @property
    def time_bins_vector(self):
        """
        Raises:
            :class:`AudioSignalException`: If :attr:`stft_data` is ``None``. Run :func:`stft`
                before accessing this.

        Returns:
            (:obj:`np.ndarray`): A 1D numpy array with time values that correspond
            to each time bin (horizontal/time axis) for :attr:`stft_data`.
        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot calculate time_bins_vector until self.stft() is run')
        return np.linspace(0.0, self.signal_duration,
                           num=self.stft_data.shape[constants.STFT_LEN_INDEX])

    @property
    def stft_length(self):
        """
        Raises:
            :class:`AudioSignalException`: If ``self.stft_dat``a is ``None``. Run :func:`stft`
                before accessing this.

        Returns:
            (int): The length of :attr:`stft_data` along the time axis. In units of hops.
        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot calculate stft_length until self.stft() is run')
        return self.stft_data.shape[constants.STFT_LEN_INDEX]

    @property
    def active_region_is_default(self):
        """
        See Also:

            * :func:`set_active_region` for a description of active regions in :class:`AudioSignal`

            * :func:`set_active_region_to_default`

        Returns:
            (bool): True if active region is the full length of :attr:`audio_data`.
        """
        return self._active_start == 0 and self._active_end == self._signal_length

    @property
    def _signal_length(self):
        """
        (int): This is the length of the full signal, not just the active region.
        """
        if self._audio_data is None:
            return None
        return self._audio_data.shape[constants.LEN_INDEX]

    @property
    def power_spectrogram_data(self):
        """
        (:obj:`np.ndarray`): Returns a real valued :obj:`np.ndarray` with power
        spectrogram data. The power spectrogram is defined as (STFT)^2, where ^2 is
        element-wise squaring of entries of the STFT. Same shape as :attr:`stft_data`.
        
        Raises:
            :class:`AudioSignalException`: if :attr:`stft_data` is ``None``. Run :func:`stft`
                before accessing this.
            
        See Also:
            * :func:`stft` to calculate the STFT before accessing this attribute.
            * :attr:`stft_data` complex-valued Short-time Fourier Transform data.
            * :attr:`power_magnitude_data`.
            * :func:`get_power_spectrogram_channel`.
            
        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot calculate power_spectrogram_data '
                                       'because self.stft_data is None')
        return np.abs(self.stft_data) ** 2

    @property
    def magnitude_spectrogram_data(self):
        """
        (:obj:`np.ndarray`): Returns a real valued ``np.array`` with magnitude spectrogram data.
        
        The power spectrogram is defined as Abs(STFT), the element-wise absolute value of every
        item in the STFT. Same shape as :attr:`stft_data`.
        
        Raises:
            AudioSignalException: if :attr:`stft_data` is ``None``. Run :func:`stft` before
                accessing this.
            
        See Also:
            * :func:`stft` to calculate the STFT before accessing this attribute.
            * :attr:`stft_data` complex-valued Short-time Fourier Transform data.
            * :attr:`power_spectrogram_data`
            * :func:`get_magnitude_spectrogram_channel`
            
        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot calculate magnitude_spectrogram_data '
                                       'because self.stft_data is None')
        return np.abs(self.stft_data)

    @property
    def log_magnitude_spectrogram_data(self):
        """
        (:obj:`np.ndarray`): Returns a real valued ``np.array`` with log magnitude spectrogram data.
        
        The log magnitude spectrogram is defined as 20*log10(Abs(STFT)). Same shape as :attr:`stft_data`.
        
        Raises:
            AudioSignalException: if :attr:`stft_data` is ``None``. Run :func:`stft` before
                accessing this.
            
        See Also:
            * :func:`stft` to calculate the STFT before accessing this attribute.
            * :attr:`stft_data` complex-valued Short-time Fourier Transform data.
            * :attr:`power_spectrogram_data`
            * :func:`get_magnitude_spectrogram_channel`
            
        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot calculate magnitude_spectrogram_data '
                                       'because self.stft_data is None')
        return 20 * np.log10(np.abs(self.stft_data) + 1e-8)

    ##################################################
    #                     I/O
    ##################################################

    def load_audio_from_file(self, input_file_path, offset=0, duration=None, new_sample_rate=None):
        # type: (str, float, float, int) -> None
        """
        Loads an audio signal into memory from a file on disc. The audio is stored in
        :class:`AudioSignal` as a :obj:`np.ndarray` of `float` s. The sample rate is read from
        the file, and this :class:`AudioSignal` object's sample rate is set from it. If
        :param:`new_sample_rate` is not ``None`` nor the same as the sample rate of the file,
        the audio will be resampled to the sample rate provided in the :param:`new_sample_rate`
        parameter. After reading the audio data into memory, the active region is set to default.

        :param:`offset` and :param:`duration` allow the user to determine how much of the audio is
        read from the file. If those are non-default, then only the values provided will be stored
        in :attr:`audio_data` (unlike with the active region, which has the entire audio data stored
        in memory but only allows access to a subset of the audio).

        See Also:
            * :func:`load_audio_from_array` to read audio data from a :obj:`np.ndarray`.

        Parameters:
            input_file_path (str): Path to input file.
            offset (float,): The starting point of the section to be extracted (seconds).
                Defaults to 0 seconds (i.e., the very beginning of the file).
            duration (float): Length of signal to load in second.
                signal_length of 0 means read the whole file. Defaults to the full
                length of the signal.
            new_sample_rate (int): If this parameter is not ``None`` or the same sample rate as
                provided by the input file, then the audio data will be resampled to the new
                sample rate dictated by this parameter.

        """
        assert offset >= 0, 'Parameter `offset` must be >= 0!'
        if duration is not None:
            assert duration >= 0, 'Parameter `duration` must be >= 0!'

        try:
            # try reading headers with soundfile for speed
            audio_info = sf.info(input_file_path)
            file_length = audio_info.duration
        except:
            # if that doesn't work try audioread
            with audioread.audio_open(os.path.realpath(input_file_path)) as input_file:
                file_length = input_file.duration

        if offset > file_length:
            raise AudioSignalException('offset is longer than signal!')

        if duration is not None and offset + duration >= file_length:
            warnings.warn('offset + duration are longer than the signal.'
                          ' Reading until end of signal...',
                          UserWarning)
        

        audio_input, self._sample_rate = librosa.load(input_file_path,
                                                      sr=None,
                                                      offset=offset,
                                                      duration=duration,
                                                      mono=False)

        self.audio_data = audio_input
        self.original_signal_length = self.signal_length

        if new_sample_rate is not None and new_sample_rate != self._sample_rate:
            warnings.warn('Input sample rate is different than the sample rate'
                          ' read from the file! Resampling...',
                          UserWarning)
            self.resample(new_sample_rate)

        self.path_to_input_file = input_file_path
        self.set_active_region_to_default()

    def load_audio_from_array(self, signal, sample_rate=constants.DEFAULT_SAMPLE_RATE):
        """
        Loads an audio signal from a :obj:`np.ndarray`. :param:`sample_rate` is the sample
        of the signal.

        See Also:
            * :func:`load_audio_from_file` to read in an audio file from disc.

        Notes:
            Only accepts float arrays and int arrays of depth 16-bits.

        Parameters:
            signal (:obj:`np.ndarray`): Array containing the audio signal sampled at
                :param:`sample_rate`.
            sample_rate (int): The sample rate of signal.
                Default is :ref:`constants.DEFAULT_SAMPLE_RATE` (44.1kHz)

        """
        assert (type(signal) == np.ndarray)

        self.path_to_input_file = None

        # Change from fixed point to floating point
        if not np.issubdtype(signal.dtype, np.floating):
            signal = signal.astype('float') / (np.iinfo(np.dtype('int16')).max + 1.0)

        self.audio_data = signal
        self.original_signal_length = self.signal_length
        self._sample_rate = sample_rate if sample_rate is not None \
            else constants.DEFAULT_SAMPLE_RATE

        self.set_active_region_to_default()

    def write_audio_to_file(self, output_file_path, sample_rate=None, verbose=False):
        """
        Outputs the audio signal data in :attr:`audio_data` to a file at :param:`output_file_path`
        with sample rate of :param:`sample_rate`.

        Parameters:
            output_file_path (str): Filename where output file will be saved.
            sample_rate (int): The sample rate to write the file at. Default is
                :attr:`sample_rate`.
            verbose (bool): Print out a message if writing the file was successful.
        """
        if self.audio_data is None:
            raise AudioSignalException("Cannot write audio file because there is no audio data.")

        if sample_rate is None:
            sample_rate = self.sample_rate

        audio_output = np.copy(self.audio_data)

        # TODO: better fix
        # convert to fixed point again
        if not np.issubdtype(audio_output.dtype, np.dtype(int).type):
            audio_output = np.multiply(
                audio_output, 
                2 ** (constants.DEFAULT_BIT_DEPTH - 1)).astype('int16')
        wav.write(output_file_path, sample_rate, audio_output.T)


    ##################################################
    #                Active Region
    ##################################################

    def set_active_region(self, start, end):
        """
        Determines the bounds of what gets returned when you access :attr:`audio_data`.
        None of the data in :attr:`audio_data` is discarded when you set the active region, it
        merely becomes inaccessible until the active region is set back to default (i.e., the full
        length of the signal).

        This is useful for reusing a single :class:`AudioSignal` object to do multiple operations on
        only select parts of the audio data.

        Warnings:
            Many functions will raise exceptions while the active region is not default. Be aware
            that adding, subtracting, concatenating, truncating, and other utilities are not
            available when the active region is not default.

        See Also:
            * :func:`set_active_region_to_default`
            * :attr:`active_region_is_default`

        Examples:
            >>> import nussl
            >>> import numpy as np
            >>> n = nussl.DEFAULT_SAMPLE_RATE  # 1 second of audio at 44.1kHz
            >>> np_sin = np.sin(np.linspace(0, 100 * 2 * np.pi, n))  # sine wave @ 100 Hz
            >>> sig = nussl.AudioSignal(audio_data_array=np_sin)
            >>> sig.signal_duration
            1.0
            >>> sig.set_active_region(0, n // 2)
            >>> sig.signal_duration
            0.5

        Args:
            start (int): Beginning of active region (in samples). Cannot be less than 0.
            end (int): End of active region (in samples). Cannot be larger than
                :attr:`signal_length`.

        """
        start, end = int(start), int(end)
        self._active_start = start if start >= 0 else 0
        self._active_end = end if end < self._signal_length else self._signal_length

    def set_active_region_to_default(self):
        """
        Resets the active region of this :class:`AudioSignal` object to its default value of the
        entire :attr:`audio_data` array.
        
        See Also:
            * :func:`set_active_region` for an explanation of active regions within the
            :class:`AudioSignal`.

        """
        self._active_start = 0
        self._active_end = self._signal_length

    ##################################################
    #               STFT Utilities
    ##################################################

    @staticmethod
    def get_window(window_type, window_length):
        """
        Wrapper around scipy.signal.get_window so one can also get the 
        popular sqrt-hann window.
        
        Args:
            window_type (str): Type of window to get (see constants.ALL_WINDOW).
            window_length (int): Length of the window
        
        Returns:
            np.ndarray: Window returned by scipy.signa.get_window
        """
        if window_type == constants.WINDOW_SQRT_HANN:
            window = np.sqrt(scipy.signal.get_window(
                'hann', window_length
            ))
        else:
            window = scipy.signal.get_window(
                window_type, window_length)
        
        return window

    def stft(self, window_length=None, hop_length=None, window_type=None, overwrite=True):
        """
        Computes the Short Time Fourier Transform (STFT) of :attr:`audio_data`.
        The results of the STFT calculation can be accessed from :attr:`stft_data`
        if :attr:`stft_data` is ``None`` prior to running this function or ``overwrite == True``

        Warning:
            If overwrite=True (default) this will overwrite any data in :attr:`stft_data`!

        Args:
            window_length (int): Amount of time (in samples) to do an FFT on
            hop_length (int): Amount of time (in samples) to skip ahead for the new FFT
            window_type (str): Type of scaling to apply to the window.
            overwrite (bool): Overwrite :attr:`stft_data` with current calculation

        Returns:
            (:obj:`np.ndarray`) Calculated, complex-valued STFT from :attr:`audio_data`, 3D numpy
            array with shape `(n_frequency_bins, n_hops, n_channels)`.

        """
        if self.audio_data is None or self.audio_data.size == 0:
            raise AudioSignalException(
                "No time domain signal (self.audio_data) to make STFT from!")

        window_length = (
            self.stft_params.window_length 
            if window_length is None
            else int(window_length)
        )
        hop_length = (
            self.stft_params.hop_length 
            if hop_length is None 
            else int(hop_length)
        )
        window_type = (
            self.stft_params.window_type 
            if window_type is None 
            else window_type
        )

        stft_data = []

        window = self.get_window(window_type, window_length)

        for chan in self.get_channels():
            _, _, _stft = scipy.signal.stft(
                chan, fs=self.sample_rate, window=window, 
                nperseg=window_length, noverlap=window_length-hop_length)
            stft_data.append(_stft)

        stft_data = np.array(stft_data).transpose((1, 2, 0))

        if overwrite:
            self.stft_data = stft_data

        return stft_data

    def istft(self, window_length=None, hop_length=None, window_type=None, overwrite=True,
              truncate_to_length=None):
        """ Computes and returns the inverse Short Time Fourier Transform (iSTFT).

        The results of the iSTFT calculation can be accessed from :attr:`audio_data`
        if :attr:`audio_data` is ``None`` prior to running this function or ``overwrite == True``

        Warning:
            If overwrite=True (default) this will overwrite any data in :attr:`audio_data`!

        Args:
            window_length (int): Amount of time (in samples) to do an FFT on
            hop_length (int): Amount of time (in samples) to skip ahead for the new FFT
            window_type (str): Type of scaling to apply to the window.
            overwrite (bool): Overwrite :attr:`stft_data` with current calculation
            truncate_to_length (int): truncate resultant signal to specified length. Default `None`.

        Returns:
            (:obj:`np.ndarray`) Calculated, real-valued iSTFT from :attr:`stft_data`, 2D numpy array
            with shape `(n_channels, n_samples)`.

        """
        if self.stft_data is None or self.stft_data.size == 0:
            raise AudioSignalException('Cannot do inverse STFT without self.stft_data!')

        window_length = (
            self.stft_params.window_length 
            if window_length is None
            else int(window_length)
        )
        hop_length = (
            self.stft_params.hop_length 
            if hop_length is None 
            else int(hop_length)
        )
        window_type = (
            self.stft_params.window_type 
            if window_type is None 
            else window_type
        )

        signals = []

        window = self.get_window(window_type, window_length)

        for stft in self.get_stft_channels():
            _, _signal = scipy.signal.istft(
                stft, fs=self.sample_rate, window=window, 
                nperseg=window_length, noverlap=window_length-hop_length)

            signals.append(_signal)

        calculated_signal = np.array(signals)

        # Make sure it's shaped correctly
        calculated_signal = np.expand_dims(calculated_signal, -1) \
            if calculated_signal.ndim == 1 else calculated_signal

        # if truncate_to_length isn't provided
        if truncate_to_length is None:
            truncate_to_length = self.original_signal_length
            if self.signal_length is not None:
                truncate_to_length = self.signal_length

        if truncate_to_length is not None and truncate_to_length > 0:
            calculated_signal = calculated_signal[:, :truncate_to_length]

        if overwrite or self.audio_data is None:
            self.audio_data = calculated_signal 

        return calculated_signal

    def apply_mask(self, mask, overwrite=False):
        """
        Applies the input mask to the time-frequency representation in this `AudioSignal` 
        object and returns a new `AudioSignal` object with the mask applied.
        
        Args:
            mask (:obj:`MaskBase`-derived object): A ``MaskBase``-derived object 
                containing a mask.
            overwrite (bool): If ``True``, this will alter ``stft_data`` in self. 
                If ``False``, this function will create a new ``AudioSignal`` object 
                with the mask applied.

        Returns:
            A new `AudioSignal`` object with the input mask applied to the STFT,
            iff ``overwrite`` is False.

        """
        if not isinstance(mask, masks.MaskBase):
            raise AudioSignalException(f'Expected MaskBase-derived object, given {type(mask)}')

        if self.stft_data is None:
            raise AudioSignalException('There is no STFT data to apply a mask to!')
        
        if mask.shape != self.stft_data.shape:
            if not mask.shape[:-1] == self.stft_data.shape:
                raise AudioSignalException(
                    'Input mask and self.stft_data are not the same shape! mask:'
                    f' {mask.shape}, self.stft_data: {self.stft_data.shape}'
                )

        masked_stft = self.stft_data * mask.mask

        if overwrite:
            self.stft_data = masked_stft
        else:
            return self.make_copy_with_stft_data(masked_stft, verbose=False)

    def ipd_ild_features(self, ch_one=0, ch_two=1):
        """
        Computes interphase difference (IPD) and interlevel difference (ILD) for a 
        stereo spectrogram. If more than two channels, this by default computes IPD/ILD
        between the first two channels. This can be specified by the arguments ch_one
        and ch_two. If only one channel, this raises an error.
        
        Args:
            ch_one (int): index of first channel to compute IPD/ILD.
            ch_two (int): index of second channel to compute IPD/ILD.

        Returns:
            ipd (np.ndarray): Interphase difference between selected channels
            ild (np.ndarray): Interlevel difference between selected channels

        """
        if self.stft_data is None:
            raise AudioSignalException("Cannot compute ipd/ild features without stft_data!")
        if self.num_channels == 1:
            raise AudioSignalException("Cannot compute ipd/ild features on mono input!")
        
        stft_ch_one = self.get_stft_channel(ch_one)
        stft_ch_two = self.get_stft_channel(ch_two)

        ild = np.abs(stft_ch_one) / (np.abs(stft_ch_two) + 1e-4)
        ild = 20 * np.log10(ild + 1e-8)

        frequencies = self.freq_vector
        ipd = np.angle(stft_ch_two * np.conj(stft_ch_one))
        ipd /= (frequencies + 1.0)[:, None]
        ipd = ipd % np.pi

        return ipd, ild

    ##################################################
    #                  Utilities
    ##################################################

    def concat(self, other):
        """ Concatenate two :class:`AudioSignal` objects (by concatenating :attr:`audio_data`).

        Puts ``other.audio_data`` after :attr:`audio_data`.

        Raises:
            AudioSignalException: If ``self.sample_rate != other.sample_rate``,
                ``self.num_channels != other.num_channels``, or ``!self.active_region_is_default``
                is ``False``.

        Args:
            other (:class:`AudioSignal`): :class:`AudioSignal` to concatenate with the current one.
            
        """
        self._verify_audio(other)

        self.audio_data = np.concatenate((self.audio_data, other.audio_data),
                                         axis=constants.LEN_INDEX)

    def truncate_samples(self, n_samples):
        """ Truncates the signal leaving only the first ``n_samples`` samples.
        This can only be done if ``self.active_region_is_default`` is True. If
        ``n_samples > self.signal_length``, then `n_samples = self.signal_length` 
        (no truncation happens).

        Raises:
            AudioSignalException: If ``self.active_region_is_default`` is ``False``.

        Args:
            n_samples: (int) number of samples that will be left.

        """
        if not self.active_region_is_default:
            raise AudioSignalException('Cannot truncate while active region is not set as default!')

        n_samples = int(n_samples)
        if n_samples > self.signal_length:
            n_samples = self.signal_length

        self.audio_data = self.audio_data[:, 0: n_samples]

    def truncate_seconds(self, n_seconds):
        """ Truncates the signal leaving only the first n_seconds.
        This can only be done if self.active_region_is_default is True.

        Args:
            n_seconds: (float) number of seconds to truncate :attr:`audio_data`.

        """
        n_samples = int(n_seconds * self.sample_rate)
        self.truncate_samples(n_samples)

    def crop_signal(self, before, after):
        """
        Get rid of samples before and after the signal on all channels. Contracts the length
        of :attr:`audio_data` by before + after. Useful to get rid of zero padding after the fact.

        Args:
            before: (int) number of samples to remove at beginning of self.audio_data
            after: (int) number of samples to remove at end of self.audio_data

        """
        if not self.active_region_is_default:
            raise AudioSignalException('Cannot crop signal while active region '
                                       'is not set as default!')
        num_samples = self.signal_length
        self.audio_data = self.audio_data[:, before:num_samples - after]
        self.set_active_region_to_default()

    def zero_pad(self, before, after):
        """ Adds zeros before and after the signal to all channels.
        Extends the length of self.audio_data by before + after.

        Raises:
            Exception: If `self.active_region_is_default`` is ``False``.

        Args:
            before: (int) number of zeros to be put before the current contents of self.audio_data
            after: (int) number of zeros to be put after the current contents fo self.audio_data

        """
        if not self.active_region_is_default:
            raise AudioSignalException('Cannot zero-pad while active region is not set as default!')
        
        self.audio_data = np.pad(self.audio_data, ((0, 0), (before, after)), 'constant')

    def add(self, other):
        """Adds two audio signal objects.

        This does element-wise addition on the :attr:`audio_data` array.

        Raises:
            AudioSignalException: If ``self.sample_rate != other.sample_rate``,
                ``self.num_channels != other.num_channels``, or
                ``self.active_region_is_default`` is ``False``.

        Parameters:
            other (:class:`AudioSignal`): Other :class:`AudioSignal` to add.

        Returns:
            (:class:`AudioSignal`): New :class:`AudioSignal` object with the sum of
            ``self`` and ``other``.
        """
        if isinstance(other, int):
            # this is so that sum(list of audio_signals) works.
            # when sum is called on a list it's evaluated as 0 + elem1 + elem2 + ...
            # so the 0 case needs to be taken care of (by doing nothing)
            return self

        self._verify_audio_arithmetic(other)

        new_signal = copy.deepcopy(self)
        new_signal.audio_data = self.audio_data + other.audio_data

        return new_signal

    def subtract(self, other):
        """Subtracts two audio signal objects.

        This does element-wise subtraction on the :attr:`audio_data` array.

        Raises:
            AudioSignalException: If ``self.sample_rate != other.sample_rate``,
                ``self.num_channels != other.num_channels``, or
                ``self.active_region_is_default`` is ``False``.

        Parameters:
            other (:class:`AudioSignal`): Other :class:`AudioSignal` to subtract.

        Returns:
            (:class:`AudioSignal`): New :class:`AudioSignal` object with the difference
            between ``self`` and ``other``.
        """
        self._verify_audio_arithmetic(other)

        other_copy = copy.deepcopy(other)
        other_copy *= -1
        return self.add(other_copy)

    def make_copy_with_audio_data(self, audio_data, verbose=True):
        """ Makes a copy of this `AudioSignal` object with :attr:`audio_data` initialized to
        the input :param:`audio_data` numpy array. The :attr:`stft_data` of the new `AudioSignal`
        object is `None`.

        Args:
            audio_data (:obj:`np.ndarray`): Audio data to be put into the new `AudioSignal` object.
            verbose (bool): If ``True`` prints warnings. If ``False``, outputs nothing.

        Returns:
            (:class:`AudioSignal`): A copy of this `AudioSignal` object with :attr:`audio_data`
            initialized to the input :param:`audio_data` numpy array.

        """
        if verbose:
            if not self.active_region_is_default:
                warnings.warn('Making a copy when active region is not default.')

            if audio_data.shape != self.audio_data.shape:
                warnings.warn('Shape of new audio_data does not match current audio_data.')

        new_signal = copy.deepcopy(self)
        new_signal.audio_data = audio_data
        new_signal.stft_data = None
        return new_signal

    def make_copy_with_stft_data(self, stft_data, verbose=True):
        """ Makes a copy of this `AudioSignal` object with :attr:`stft_data` initialized to the
        input :param:`stft_data` numpy array. The :attr:`audio_data` of the new `AudioSignal`
        object is `None`.

        Args:
            stft_data (:obj:`np.ndarray`): STFT data to be put into the new `AudioSignal` object.

        Returns:
            (:class:`AudioSignal`): A copy of this `AudioSignal` object with :attr:`stft_data`
            initialized to the input :param:`stft_data` numpy array.

        """
        if verbose:
            if not self.active_region_is_default:
                warnings.warn('Making a copy when active region is not default.')

            if stft_data.shape != self.stft_data.shape:
                warnings.warn('Shape of new stft_data does not match current stft_data.')

        new_signal = copy.deepcopy(self)
        new_signal.stft_data = stft_data
        new_signal.original_signal_length = self.original_signal_length
        new_signal.audio_data = None
        return new_signal

    def rms(self):
        """ Calculates the root-mean-square of :attr:`audio_data`.
        
        Returns:
            (float): Root-mean-square of :attr:`audio_data`.

        """
        return np.sqrt(np.mean(np.square(self.audio_data)))

    def apply_gain(self, value):
        """
        Apply a gain to :attr;`audio_data`

        Args:
            value (float): amount to multiply self.audio_data by

        Returns:
            (:class:`AudioSignal`): This :class:`AudioSignal` object with the gain applied.

        """
        if not isinstance(value, numbers.Real):
            raise AudioSignalException('Can only multiply/divide by a scalar!')

        self.audio_data = self.audio_data * value
        return self

    def resample(self, new_sample_rate):
        """
        Resample the data in :attr:`audio_data` to the new sample rate provided by
        :param:`new_sample_rate`. If the :param:`new_sample_rate` is the same as :attr:`sample_rate`
        then nothing happens.

        Args:
            new_sample_rate (int): The new sample rate of :attr:`audio_data`.

        """

        if new_sample_rate == self.sample_rate:
            warnings.warn('Cannot resample to the same sample rate.')
            return

        resampled_signal = []

        for channel in self.get_channels():
            resampled_channel = librosa.resample(channel, self.sample_rate, new_sample_rate)
            resampled_signal.append(resampled_channel)

        self.audio_data = np.array(resampled_signal)
        self._sample_rate = new_sample_rate

    ##################################################
    #              Channel Utilities
    ##################################################

    def _verify_get_channel(self, n):
        if n >= self.num_channels:
            raise AudioSignalException(
                f'Cannot get channel {n} when this object only has {self.num_channels}'
                ' channels! (0-based)'
            )

        if n < 0:
            raise AudioSignalException(
                f'Cannot get channel {n}. This will cause unexpected results'
            )

    def get_channel(self, n):
        """Gets audio data of n-th channel from :attr:`audio_data` as a 1D :obj:`np.ndarray`
        of shape ``(n_samples,)``.

        Parameters:
            n (int): index of channel to get. **0-based**

        See Also:
            * :func:`get_channels`: Generator for looping through channels of :attr:`audio_data`.
            * :func:`get_stft_channel`: Gets stft data from a specific channel.
            * :func:`get_stft_channels`: Generator for looping through channels from
            :attr:`stft_data`.

        Raises:
            :class:`AudioSignalException`: If not ``0 <= n < self.num_channels``.
            
        Returns:
            (:obj:`np.array`): The audio data in the n-th channel of the signal, 1D

        """
        self._verify_get_channel(n)

        return np.asfortranarray(utils._get_axis(self.audio_data, constants.CHAN_INDEX, n))

    def get_channels(self):
        """Generator that will loop through channels of :attr:`audio_data`.

        See Also:
            * :func:`get_channel`: Gets audio data from a specific channel.
            * :func:`get_stft_channel`: Gets stft data from a specific channel.
            * :func:`get_stft_channels`: Generator to loop through channels of :attr:`stft_data`.

        Yields:
            (:obj:`np.array`): The audio data in the next channel of this signal as a
            1D ``np.ndarray``.

        """
        for i in range(self.num_channels):
            yield self.get_channel(i)

    def get_stft_channel(self, n):
        """Returns STFT data of n-th channel from :attr:`stft_data` as a 2D ``np.ndarray``.

        Args:
            n: (int) index of stft channel to get. **0-based**

        See Also:
            * :func:`get_stft_channels`: Generator to loop through channels from :attr:`stft_data`.
            * :func:`get_channel`: Gets audio data from a specific channel.
            * :func:`get_channels`: Generator to loop through channels of :attr:`audio_data`.

        Raises:
            :class:`AudioSignalException`: If not ``0 <= n < self.num_channels``.

        Returns:
            (:obj:`np.array`): the STFT data in the n-th channel of the signal, 2D

        """
        if self.stft_data is None:
            raise AudioSignalException('Cannot get STFT data before STFT is calculated!')

        self._verify_get_channel(n)

        return utils._get_axis(self.stft_data, constants.STFT_CHAN_INDEX, n)

    def get_stft_channels(self):
        """Generator that will loop through channels of :attr:`stft_data`.

        See Also:
            * :func:`get_stft_channel`: Gets stft data from a specific channel.
            * :func:`get_channel`: Gets audio data from a specific channel.
            * :func:`get_channels`: Generator to loop through channels of :attr:`audio_data`.

        Yields:
            (:obj:`np.array`): The STFT data in the next channel of this signal as a
            2D ``np.ndarray``.

        """
        for i in range(self.num_channels):
            yield self.get_stft_channel(i)

    def make_audio_signal_from_channel(self, n):
        """
        Makes a new :class:`AudioSignal` object from with data from channel ``n``.
        
        Args:
            n (int): index of channel to make a new signal from. **0-based**

        Returns:
            (:class:`AudioSignal`) new :class:`AudioSignal` object with only data from
            channel ``n``.

        """
        new_signal = copy.copy(self)
        new_signal.audio_data = self.get_channel(n)
        return new_signal

    def get_power_spectrogram_channel(self, n):
        """ Returns the n-th channel from ``self.power_spectrogram_data``.

        Raises:
            Exception: If not ``0 <= n < self.num_channels``.

        Args:
            n: (int) index of power spectrogram channel to get **0-based**

        Returns:
            (:obj:`np.array`): the power spectrogram data in the n-th channel of the signal, 1D
        """
        self._verify_get_channel(n)

        # np.array helps with duck typing
        return utils._get_axis(np.array(self.power_spectrogram_data), 
                               constants.STFT_CHAN_INDEX, n)

    def get_magnitude_spectrogram_channel(self, n):
        """ Returns the n-th channel from ``self.magnitude_spectrogram_data``.

        Raises:
           Exception: If not ``0 <= n < self.num_channels``.

        Args:
            n: (int) index of magnitude spectrogram channel to get **0-based**

        Returns:
            (:obj:`np.array`): the magnitude spectrogram data in the n-th channel of the signal, 1D
        """
        self._verify_get_channel(n)

        # np.array helps with duck typing
        return utils._get_axis(np.array(self.magnitude_spectrogram_data),
                               constants.STFT_CHAN_INDEX, n)

    def to_mono(self, overwrite=True, keep_dims=False):
        """ Converts :attr:`audio_data` to mono by averaging every sample.

        Args:
            overwrite (bool): If `True` this function will overwrite :attr:`audio_data`.
            keep_dims (bool): If `False` this function will return a 1D array,
                else will return array with shape `(1, n_samples)`.

        Warning:
            If ``overwrite=True`` (default) this will overwrite any data in :attr:`audio_data`!

        Returns:
            (:obj:`np.array`): Mono-ed version of :attr:`audio_data`.

        """
        mono = np.mean(self.audio_data, axis=constants.CHAN_INDEX, keepdims=keep_dims)

        if overwrite:
            self.audio_data = mono
        return mono

    ##################################################
    #              Operator overloading
    ##################################################

    def __add__(self, other):
        return self.add(other)

    def __radd__(self, other):
        return self.add(other)

    def __sub__(self, other):
        return self.subtract(other)

    def _verify_audio(self, other):
        if self.num_channels != other.num_channels:
            raise AudioSignalException('Cannot do operation with two signals that have '
                                       'a different number of channels!')

        if self.sample_rate != other.sample_rate:
            raise AudioSignalException('Cannot do operation with two signals that have '
                                       'different sample rates!')

    def _verify_audio_arithmetic(self, other):
        self._verify_audio(other)

        if self.signal_length != other.signal_length:
            raise AudioSignalException('Cannot do arithmetic with signals of different length!')

    def __iadd__(self, other):
        return self + other

    def __isub__(self, other):
        return self - other

    def __mul__(self, value):
        if not isinstance(value, numbers.Real):
            raise AudioSignalException('Can only multiply/divide by a scalar!')

        return self.make_copy_with_audio_data(np.multiply(self.audio_data, value), verbose=False)

    def __div__(self, value):
        if not isinstance(value, numbers.Real):
            raise AudioSignalException('Can only multiply/divide by a scalar!')

        return self.make_copy_with_audio_data(np.divide(self.audio_data, float(value)),
                                              verbose=False)

    def __truediv__(self, value):
        return self.__div__(value)

    def __itruediv__(self, value):
        return self.__idiv__(value)

    def __imul__(self, value):
        return self.apply_gain(value)

    def __idiv__(self, value):
        return self.apply_gain(1 / float(value))

    def __len__(self):
        return self.signal_length

    def __eq__(self, other):
        for k, v in list(self.__dict__.items()):
            if isinstance(v, np.ndarray):
                if not np.array_equal(v, other.__dict__[k]):
                    return False
            elif v != other.__dict__[k]:
                return False
        return True

    def __ne__(self, other):
        return not self == other




class AudioSignalException(Exception):
    """
    Exception class for :class:`AudioSignal`.
    """
    pass
