# In this demo two sound sources are superimposed synthesize a mixture. 
# A mask is generated by thresholding the spectrogram of one of 
# the two sources and used to separate the source from the mixture. 
# Separated sources are then transformed back to the time domain.

from scipy.io.wavfile import read,write
import matplotlib.pyplot as plt
plt.interactive('True')
import numpy as np
from f_stft import f_stft
from f_istft import f_istft


# close all open figure windows
plt.close('all') 

# Load the audio files
fs,s1=read('/Users/fpishdadian/SourceSeparation/Audio Samples/Input/K0140.wav') 
fs,s2=read('/Users/fpishdadian/SourceSeparation/Audio Samples/Input/K0149.wav')

# scale to -1.0 to 1.0
convert_16_bit = float(2**15)
s1 = s1 / (convert_16_bit + 1.0)
s2 = s2 / (convert_16_bit + 1.0)


Ls=np.array([len(s1),len(s2)]); Ls=Ls.min()
s1=np.mat(s1[0:Ls]); s2=np.mat(s2[0:Ls])
ts=np.mat(np.arange(Ls)/float(fs))

x=s1+s2

# Generate spectrograms
L=2048
win='Hamming'
ovp=int(0.5*L)
nfft=L
mkplot=1
fmax=5000

plt.figure(1)  
S1,Ps1,F,T = f_stft(s1,L,win,ovp,fs,nfft=nfft,mkplot=mkplot,fmax=fmax) 
plt.title('Source 1')

plt.figure(2)
S2,Ps2,F,T = f_stft(s2,L,win,ovp,fs,nfft=nfft,mkplot=mkplot,fmax=fmax)
plt.title('Source 2')

plt.figure(3)  
X,Px,F,T = f_stft(x,L,win,ovp,fs,nfft=nfft,mkplot=mkplot,fmax=fmax)
plt.title('Mixture')

# Make a mask
Ps1=Ps1/Ps1.max()
M=Ps1>=0.0001

plt.figure(4)
TT=np.tile(T,(len(F),1))
FF=np.tile(F.T,(len(T),1)).T
plt.pcolormesh(TT,FF,M)
plt.xlabel('Time')
plt.ylabel('Frequency')
plt.axis('tight')
plt.ylim(0,fmax)
plt.show()


# Separate by masking
SM1=M*X
SM2=(1-M)*X

plt.figure(5)
plt.subplot(2,1,1)
SP1=10*np.log10(np.abs(Px))*M
plt.pcolormesh(TT,FF,SP1)
plt.xlabel('Time')
plt.ylabel('Frequency')
plt.axis('tight')
plt.ylim(0,fmax)
plt.show()

plt.subplot(2,1,2)
SP2=10*np.log10(np.abs(Px))*(1-M)
plt.pcolormesh(TT,FF,SP2)
plt.xlabel('Time')
plt.ylabel('Frequency')
plt.axis('tight')
plt.ylim(0,fmax)
plt.show()

# Convert to time series
sm1,t1 = f_istft(SM1,L,win,ovp,fs)
sm2,t2 = f_istft(SM2,L,win,ovp,fs)

# plot the separated time signals

plt.figure(7)
plt.subplot(2,1,1)
plt.title('Time-domain Audio Signal')
plt.plot(t1,sm1,'b-')
plt.plot(ts.T,s1.T,'r-')
plt.xlabel('t(sec)')
plt.ylabel('s_1(t)')
plt.legend(['estimated','original'])
plt.show()

plt.subplot(2,1,2)
plt.title('Time-domain Audio Signal')
plt.plot(t2,sm2,'b-')
plt.plot(ts.T,s2.T,'r-')
plt.xlabel('t(sec)')
plt.ylabel('s_2(t)')
plt.legend(['estimated','original'])
plt.show()

# record the separated signals in .wav files

# scale to -32768 -- 32767
sm1 = np.int16( sm1 * convert_16_bit )
sm2 = np.int16( sm2 * convert_16_bit )

write('/Users/fpishdadian/SourceSeparation/Audio Samples/Output/sepSource1.wav',fs,sm1)
write('/Users/fpishdadian/SourceSeparation/Audio Samples/Output/sepSource2.wav',fs,sm2)



