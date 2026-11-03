"""Resolve real ttk state maps: inherited light colors must not leak into dark controls."""
import tkinter as tk
import unittest
from app.ui.theme import apply


def contrast(first,second):
    def luminance(color):
        values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
    a,b=sorted((luminance(first),luminance(second)))
    return (b+.05)/(a+.05)


class ThemeContrastTests(unittest.TestCase):
    def test_button_text_and_dropdown_arrows_are_readable_in_every_state(self):
        root=tk.Tk();root.withdraw()
        try:
            for mode in ('dark','light'):
                style=apply(root,mode)
                for state in ((),('active',),('pressed',),('focus',),('disabled',),('disabled','active')):
                    for name in ('TButton','Primary.TButton','TMenubutton'):
                        with self.subTest(mode=mode,state=state,style=name):
                            self.assertGreaterEqual(contrast(style.lookup(name,'foreground',state),style.lookup(name,'background',state)),4.5)
                    for name in ('TMenubutton','TCombobox','TSpinbox'):
                        with self.subTest(mode=mode,state=state,arrow=name):
                            arrow=style.lookup(name,'arrowcolor',state)
                            self.assertTrue(arrow,'Explicit arrow color required')
                            self.assertGreaterEqual(contrast(arrow,style.lookup(name,'background',state)),4.5)
        finally:root.destroy()

    def test_checkbox_and_radio_marks_remain_visible(self):
        root=tk.Tk();root.withdraw()
        try:
            for mode in ('dark','light'):
                style=apply(root,mode)
                for name in ('TCheckbutton','TRadiobutton'):
                    for state in ((),('selected',),('selected','active'),('selected','disabled'),('alternate',),('pressed',)):
                        with self.subTest(mode=mode,state=state,style=name):
                            self.assertGreaterEqual(contrast(style.lookup(name,'foreground',state),style.lookup(name,'indicatorbackground',state)),4.5)
        finally:root.destroy()


if __name__=='__main__':unittest.main(verbosity=2)
