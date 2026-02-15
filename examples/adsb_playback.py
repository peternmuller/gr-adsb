#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: ADS-B Playback
# Author: Matt Hostetter, Peter Muller
# GNU Radio version: v3.11.0.0git-1082-g205e1fdf

from gnuradio import blocks
from gnuradio import gr, pdu
from gnuradio import zeromq
import gnuradio.adsb as adsb
import sqlite
import threading
from gnuradio import gr
from gnuradio.filter import firdes
from gnuradio.fft import window
import sys
import signal
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation




class adsb_playback(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "ADS-B Playback", catch_exceptions=True)

        ##################################################
        # Variables
        ##################################################
        self.samp_rate = samp_rate = 2e6

        ##################################################
        # Blocks
        ##################################################

        self.zeromq_pub_msg_sink_0 = zeromq.pub_msg_sink('tcp://127.0.0.1:5001', 10, True)
        self.sqlite_timed_source_0 = sqlite.timed_source('/home/peter/gr-sqlite/adsb-decoded.db', 'decoded', 'data', 'timestamp', None, 1.0)
        self.pdu_tagged_stream_to_pdu_0 = pdu.tagged_stream_to_pdu(gr.types.byte_t, 'packet_len')
        self.pdu_pdu_to_tagged_stream_0 = pdu.pdu_to_tagged_stream(gr.types.byte_t, 'packet_len')
        self.blocks_throttle2_0 = blocks.throttle( gr.sizeof_char*1, samp_rate, True, 0 if "auto" == "auto" else max( int(float(0.1) * samp_rate) if "auto" == "time" else int(0.1), 1) )
        self.adsb_decoder_0 = adsb.decoder("Extended Squitter Only", "None", "Brief")


        ##################################################
        # Connections
        ##################################################
        self.msg_connect((self.adsb_decoder_0, 'decoded'), (self.zeromq_pub_msg_sink_0, 'in'))
        self.msg_connect((self.pdu_tagged_stream_to_pdu_0, 'pdus'), (self.adsb_decoder_0, 'demodulated'))
        self.msg_connect((self.sqlite_timed_source_0, 'pdu'), (self.pdu_pdu_to_tagged_stream_0, 'pdus'))
        self.connect((self.blocks_throttle2_0, 0), (self.pdu_tagged_stream_to_pdu_0, 0))
        self.connect((self.pdu_pdu_to_tagged_stream_0, 0), (self.blocks_throttle2_0, 0))


    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.blocks_throttle2_0.set_sample_rate(self.samp_rate)




def main(top_block_cls=adsb_playback, options=None):
    tb = top_block_cls()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    tb.start()

    try:
        input('Press Enter to quit: ')
    except EOFError:
        pass
    tb.stop()
    tb.wait()


if __name__ == '__main__':
    main()
