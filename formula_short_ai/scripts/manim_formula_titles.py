from manim import *


class MythicFormulaTitles(Scene):
    """Optional clean formula title render for Manim users.

    Run from the workspace root with:
    manim -pql formula_short_ai/scripts/manim_formula_titles.py MythicFormulaTitles
    """

    def construct(self):
        formulas = [
            ("Pythagorean Theorem", r"a^2+b^2=c^2"),
            ("Euler Identity", r"e^{i\pi}+1=0"),
            ("Quadratic Formula", r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}"),
            ("Fourier Transform", r"\hat f(\xi)=\int_{-\infty}^{\infty}f(x)e^{-2\pi i x\xi}\,dx"),
            ("Gaussian Integral", r"\int_{-\infty}^{\infty} e^{-x^2}\,dx=\sqrt{\pi}"),
            ("Newton's Law", r"F=ma"),
        ]

        self.camera.background_color = "#0b0b0c"
        for title, formula in formulas:
            heading = Text(title, color="#d4b36c", font_size=34).to_edge(UP)
            math = MathTex(formula, color="#f0dfbb").scale(1.25)
            glow = math.copy().set_color("#7a5526").set_opacity(0.45).scale(1.02)
            self.play(FadeIn(heading, shift=DOWN * 0.2), FadeIn(glow), Write(math), run_time=1.2)
            self.wait(0.8)
            self.play(FadeOut(heading), FadeOut(glow), FadeOut(math), run_time=0.5)
