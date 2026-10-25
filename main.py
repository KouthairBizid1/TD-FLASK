import os
import secrets
from datetime import date
from decimal import Decimal

import click
from flask import Flask, flash, redirect, render_template, url_for
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from passlib.hash import pbkdf2_sha256
from sqlalchemy import CheckConstraint, event, select
from sqlalchemy.exc import IntegrityError
from wtforms import DateField, DecimalField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, ValidationError


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "mysql+pymysql://root@localhost:3306/scol"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)


class User(db.Model):
    __tablename__ = "user"

    username = db.Column(db.String(80), primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Classe(db.Model):
    __tablename__ = "classe"
    __table_args__ = (CheckConstraint("NbrEtud >= 0"),)

    CodClass = db.Column(db.String(20), primary_key=True)
    NomClass = db.Column(db.String(80), unique=True, nullable=False)
    NbrEtud = db.Column(db.Integer, nullable=False, default=0)
    etudiants = db.relationship("Etudiant", back_populates="classe", cascade="all, delete-orphan")


class Etudiant(db.Model):
    __tablename__ = "etudiant"

    NCE = db.Column(db.String(20), primary_key=True)
    Nom = db.Column(db.String(80), nullable=False)
    Prenom = db.Column(db.String(80), nullable=False)
    DateNais = db.Column(db.Date, nullable=False)
    LieuNais = db.Column(db.String(100), nullable=False)
    CodClass = db.Column(
        db.String(20),
        db.ForeignKey("classe.CodClass", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    classe = db.relationship("Classe", back_populates="etudiants")
    absences = db.relationship("Absence", back_populates="etudiant", cascade="all, delete-orphan")


class Matiere(db.Model):
    __tablename__ = "matiere"

    CodMat = db.Column(db.String(20), primary_key=True)
    IntMat = db.Column(db.String(100), nullable=False)
    Description = db.Column(db.Text, nullable=False, default="")
    absences = db.relationship("Absence", back_populates="matiere", cascade="all, delete-orphan")


class Absence(db.Model):
    __tablename__ = "absence"
    __table_args__ = (CheckConstraint("NHA > 0"),)

    CodMat = db.Column(
        db.String(20),
        db.ForeignKey("matiere.CodMat", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    NCE = db.Column(
        db.String(20),
        db.ForeignKey("etudiant.NCE", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    DateA = db.Column(db.Date, primary_key=True)
    NHA = db.Column(db.Numeric(5, 2), nullable=False)
    matiere = db.relationship("Matiere", back_populates="absences")
    etudiant = db.relationship("Etudiant", back_populates="absences")


@event.listens_for(Etudiant, "after_insert")
def incrementer_effectif(mapper, connection, etudiant):
    connection.execute(
        Classe.__table__.update()
        .where(Classe.CodClass == etudiant.CodClass)
        .values(NbrEtud=Classe.NbrEtud + 1)
    )


class UserForm(FlaskForm):
    username = StringField("Nom d'utilisateur", validators=[DataRequired(), Length(max=80)])
    email = StringField("Adresse e-mail", validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField("Mot de passe", validators=[DataRequired(), Length(min=8, max=128)])
    confirmation = PasswordField(
        "Confirmer le mot de passe",
        validators=[DataRequired(), EqualTo("password", message="Les mots de passe sont différents.")],
    )
    submit = SubmitField("Ajouter")


class ClasseForm(FlaskForm):
    CodClass = StringField("Code classe", validators=[DataRequired(), Length(max=20)])
    NomClass = StringField("Nom de la classe", validators=[DataRequired(), Length(max=80)])
    submit = SubmitField("Ajouter")


class EtudiantForm(FlaskForm):
    NCE = StringField("Numéro de carte étudiant", validators=[DataRequired(), Length(max=20)])
    Nom = StringField("Nom", validators=[DataRequired(), Length(max=80)])
    Prenom = StringField("Prénom", validators=[DataRequired(), Length(max=80)])
    DateNais = DateField("Date de naissance", validators=[DataRequired()])
    LieuNais = StringField("Lieu de naissance", validators=[DataRequired(), Length(max=100)])
    CodClass = SelectField("Classe", validators=[DataRequired()])
    submit = SubmitField("Ajouter")

    def validate_DateNais(self, field):
        if field.data > date.today():
            raise ValidationError("La date de naissance ne peut pas être dans le futur.")


class MatiereForm(FlaskForm):
    CodMat = StringField("Code matière", validators=[DataRequired(), Length(max=20)])
    IntMat = StringField("Intitulé", validators=[DataRequired(), Length(max=100)])
    Description = TextAreaField("Description", validators=[Length(max=2000)])
    submit = SubmitField("Ajouter")


class AbsenceForm(FlaskForm):
    NCE = SelectField("Étudiant", validators=[DataRequired()])
    CodMat = SelectField("Matière", validators=[DataRequired()])
    DateA = DateField("Date d'absence", validators=[DataRequired()])
    NHA = DecimalField(
        "Nombre d'heures d'absence",
        places=2,
        validators=[DataRequired(), NumberRange(min=Decimal("0.01"), max=Decimal("999.99"))],
    )
    submit = SubmitField("Ajouter")

    def validate_NHA(self, field):
        if not field.data.is_finite():
            raise ValidationError("Saisissez un nombre fini.")
        if field.data.as_tuple().exponent < -2:
            raise ValidationError("Saisissez au maximum deux décimales.")


def enregistrer(objet, destination):
    db.session.add(objet)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        app.logger.warning("Insertion refusée : doublon ou référence invalide.", exc_info=True)
        flash("Enregistrement impossible : ce code, cet e-mail ou cette absence existe déjà, "
              "ou une référence n'est plus disponible.", "error")
        return None
    flash("Enregistrement ajouté.", "success")
    return redirect(url_for(destination))


@app.route("/")
def index():
    classes = db.session.scalars(select(Classe).order_by(Classe.NomClass)).all()
    return render_template("index.html", classes=classes)


@app.route("/users/ajouter", methods=["GET", "POST"])
def ajouter_user():
    form = UserForm()
    if form.validate_on_submit():
        reponse = enregistrer(
            User(
                username=form.username.data.strip(),
                email=form.email.data.strip().lower(),
                password=pbkdf2_sha256.hash(form.password.data),
            ),
            "ajouter_user",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter un utilisateur", form=form)


@app.route("/classes/ajouter", methods=["GET", "POST"])
def ajouter_classe():
    form = ClasseForm()
    if form.validate_on_submit():
        reponse = enregistrer(
            Classe(CodClass=form.CodClass.data.strip(), NomClass=form.NomClass.data.strip()),
            "index",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter une classe", form=form)


@app.route("/etudiants/ajouter", methods=["GET", "POST"])
def ajouter_etudiant():
    form = EtudiantForm()
    form.CodClass.choices = [
        (classe.CodClass, classe.NomClass)
        for classe in db.session.scalars(select(Classe).order_by(Classe.NomClass))
    ]
    if form.validate_on_submit():
        reponse = enregistrer(
            Etudiant(
                NCE=form.NCE.data.strip(),
                Nom=form.Nom.data.strip(),
                Prenom=form.Prenom.data.strip(),
                DateNais=form.DateNais.data,
                LieuNais=form.LieuNais.data.strip(),
                CodClass=form.CodClass.data,
            ),
            "index",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter un étudiant", form=form)


@app.route("/matieres/ajouter", methods=["GET", "POST"])
def ajouter_matiere():
    form = MatiereForm()
    if form.validate_on_submit():
        reponse = enregistrer(
            Matiere(
                CodMat=form.CodMat.data.strip(),
                IntMat=form.IntMat.data.strip(),
                Description=form.Description.data.strip(),
            ),
            "ajouter_matiere",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter une matière", form=form)


@app.route("/absences/ajouter", methods=["GET", "POST"])
def ajouter_absence():
    form = AbsenceForm()
    form.NCE.choices = [
        (etudiant.NCE, f"{etudiant.NCE} - {etudiant.Nom} {etudiant.Prenom}")
        for etudiant in db.session.scalars(select(Etudiant).order_by(Etudiant.Nom, Etudiant.Prenom))
    ]
    form.CodMat.choices = [
        (matiere.CodMat, matiere.IntMat)
        for matiere in db.session.scalars(select(Matiere).order_by(Matiere.IntMat))
    ]
    if form.validate_on_submit():
        reponse = enregistrer(
            Absence(
                NCE=form.NCE.data,
                CodMat=form.CodMat.data,
                DateA=form.DateA.data,
                NHA=form.NHA.data,
            ),
            "index",
        )
        if reponse is not None:
            return reponse
    return render_template("formulaire.html", titre="Ajouter une absence", form=form)


@app.route("/classes/<cod_class>/etudiants/<nce>/absences")
def absences_etudiant(cod_class, nce):
    etudiant = db.first_or_404(
        select(Etudiant).where(Etudiant.NCE == nce, Etudiant.CodClass == cod_class)
    )
    absences = db.session.scalars(
        select(Absence)
        .where(Absence.NCE == etudiant.NCE)
        .order_by(Absence.DateA, Absence.CodMat)
    ).all()
    return render_template("absece_Etudiant.html", etudiant=etudiant, absences=absences)


@app.cli.command("init-db")
def init_db():
    with app.app_context():
        db.create_all()
    click.echo("Les tables de la base scol ont été créées.")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")