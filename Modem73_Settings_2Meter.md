# Modem73 Settings for 2-Meter

## Carrier Sense Multiple Access (CSMA)

Recommended CSMA Settings

- CSMA Mode: sync (Uses the internal busy detector)
- CSMA Band: vhf (Calibrates the underlying timing calculations specifically for VHF propagation and standard radio turnaround characteristics)
- CSMA Preset: relaxed

**Launching via Command Line**

./modem73 --csma-mode sync --csma-band vhf --csma-preset relaxed

## 2-Meter Settings (Modem73)

- Modulation: BPSK
	- I saw a recommendation to use QAM4096 for 2-Meter instead of the default BPSK. My Ubuntu configuration sent messages that were received by my MacOS system but Ubuntu did not decode the messages sent from MacOS so I changed back to the default. 
- RX Decoders: MFSK OFF. Leaving it enabled on VHF frequently causes false positives in your log files and utils dashboard. 
- Squelch / Level Threshold: Make sure your radio squelch and the modem's level threshold are tuned properly so the CSMA sync busy detector can reliably determine when the channel is clear before transmitting.

## 2-Meter Settings (Radio)

## Modem73 Installation Notes

The installation notes on the Modem73 are very simple and worked as described for me. I installed on MacOS and Linux using AIOC for both.

### Linux
You will need to add your Linux user to the DIALOUT group if you haven't already done so. You may also need to change the settings on the serial port device. My testing was done on a recent version of Ubuntu. Depending on what else is configured or running your system, that final digit of the device name bay be a higher number than zero.

sudo chmod g+rw /dev/ttyACM0

sudo usermod -aG dialout $USER

### MacOS

The device name for the AIOC serial port is very long, such as "/dev/tty.usbmodemabc4fadb5". This is too long to display on the Modem73 config screen. I created a symbolic link in my working directory and used that shorter name "dev_aioc" in Modem73 config.

ln -s /dev/tty.usbmodemabc4fadb5 dev_aioc


