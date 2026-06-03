alias src='source ~/.bash_profile'
alias profile='vi ~/.bash_profile'
alias del='echo "" > '
alias c='clear'
alias ll='ls -lrht'
alias dba="python3 ~/pg-ai-agency/rag/expert.py -v"
alias pg="sudo su - postgres -c \"psql rag_db\""
alias save="~/pg-ai-agency/save.sh"
alias bdb="sudo -u postgres pg_dump -d rag_db | tee /home/cs2081716/pg-ai-agency/dbbkp/rag_db.sql > /dev/null"
cd /home/cs2081716/pg-ai-agency
source .pgvenv/bin/activate

sudo sysctl -w vm.nr_hugepages=2150
echo "vm.nr_hugepages=2150" | sudo tee -a /etc/sysctl.conf
