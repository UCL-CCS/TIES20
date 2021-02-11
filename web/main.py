import datetime
import pathlib
import subprocess
import zipfile
import os

from flask import Flask, render_template, request, redirect, send_file
from iteration_utilities import deepflatten

app = Flask(__name__)


# the working directory
work_dir = pathlib.Path('/home/dresio/tiesclients')

@app.route('/')
def hello_world():
   return render_template('main.html')

@app.route("/upload-image", methods=["GET", "POST"])
def upload_image():
    if request.method == "POST":
        # if request.form['password'] != 'haslo':
        #     return "Wrong Password"

        # net charge
        not_validated_nc = request.form['net_charge']
        if not_validated_nc.startswith('-'):
            nc_negative = True
            not_validated_nc = not_validated_nc[1:]
        else:
            nc_negative = False
        if not_validated_nc.isdigit():
            net_charge = int(request.form['net_charge'])
        else:
            return 'Net ligand charge is not an integer'

        # check the files
        if request.files['ligand_ini'].filename == '' or request.files['ligand_fin'].filename == '':
            return 'One of the ligands was not uploaded'

        # create a dedicated directory (date and metadata) for the request where to save the files etc
        session_dir = work_dir / f'{datetime.datetime.now().strftime("%d-%m-%Y-%H:%M:%S:%f")}'
        # todo - save IP address, and other info related in the request (entire request?)
        session_dir.mkdir()

        # save the files
        request.files['ligand_ini'].save(session_dir / request.files['ligand_ini'].filename)
        request.files['ligand_fin'].save(session_dir / request.files['ligand_fin'].filename)

        # redirect?
        # run TIES on the underlying system
        # load antechamber
        ambertools = 'source /home/dresio/software/amber18install/amber.sh'
        # activate ties env
        loadties = 'source /home/dresio/software/virtualenvs/tiesdev/bin/activate '
        # run it
        try:
            output = subprocess.check_output([f'{ambertools} ; cd {session_dir} && {loadties} ; '
                                              f'ties create '
                                                f'-l {request.files["ligand_ini"].filename} '
                                                    f'{request.files["ligand_fin"].filename} '
                                                f'-nc {net_charge}'],
                            shell=True)
            # todo apply the /n to be actually not escaped characters?
            print('done')
        except subprocess.CalledProcessError:
            print('Error')

        # zip altogether
        os.chdir(session_dir)
        with zipfile.ZipFile(session_dir / 'ties20.zip', 'w') as myzip:
            for i in (session_dir / 'ties20').glob('**/*'):
                print('rel', i.relative_to((session_dir / 'ties20')))
                myzip.write(i.relative_to(session_dir))
        zipped_output = session_dir / 'ties20.zip'

        return send_file(zipped_output, as_attachment=True,
                         attachment_filename=f'ties20_{request.files["ligand_ini"].filename}_{request.files["ligand_fin"].filename}.zip')

    return render_template("public/upload_image.html")

if __name__ == '__main__':
   app.run()